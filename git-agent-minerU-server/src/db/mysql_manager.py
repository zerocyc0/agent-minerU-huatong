# encoding: utf-8
# @file: mysql_manager.py
# @desc: MySQL 数据访问。将解析出的物料条目保存到 material_analysis 表。
#        一个文件用相同的 file_sn(文件编号)，每条数据用 data_sn(数据顺序号) 区分，
#        联合主键 (file_sn, data_sn)。file_name 保存分析的文件名。
#        staff_id(工号) 由客户端传入。表结构不存在时自动创建（含数据库）。
import re
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

from config_manager import get_mysql_config

# 中文返回字段 -> 数据表英文字段
_CN_TO_EN = {
    "型号": "model",
    "规格": "spec",
    "电压": "voltage",
    "颜色": "color",
    "标准": "standard",
    "数量": "quantity",
    "单位": "unit",
}

_lock = threading.Lock()
_seq = 0            # 同一秒内的自增序号
_seq_sec = ""       # 当前序号对应的秒（yyyyMMddHHmmss）


def generate_file_sn() -> str:
    """生成文件编号（主键）：MA + 14位时间戳 + 4位秒内序号，线程安全"""
    global _seq, _seq_sec
    with _lock:
        sec = datetime.now().strftime("%Y%m%d%H%M%S")
        if sec != _seq_sec:
            _seq_sec = sec
            _seq = 0
        _seq += 1
        return f"MA{sec}{_seq:04d}"


def _to_number(value: Any) -> Optional[float]:
    """数量转数值；无法转换返回 None"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(m.group(0)) if m else None


def _connect(include_db: bool = True):
    """创建 PyMySQL 连接；include_db=False 时不指定库（用于建库）"""
    import pymysql
    cfg = get_mysql_config()
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"] if include_db else None,
        charset=cfg["charset"],
        autocommit=False,
        connect_timeout=10,
    )


def _table_has_column(cur, table: str, col: str) -> bool:
    """检查表是否已存在某列"""
    cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (col,))
    return cur.fetchone() is not None


def _table_pk_cols(cur, table: str) -> list:
    """返回表的主键列名列表"""
    cur.execute(f"SHOW KEYS FROM `{table}` WHERE Key_name='PRIMARY'")
    return [row[4] for row in cur.fetchall()]  # Column_name 是第5列


def init_db(logger=None) -> bool:
    """确保数据库与表存在；成功返回 True，失败返回 False。
    若旧表以 file_sn 单列为主键，自动迁移为 (file_sn, data_sn) 联合主键。"""
    cfg = get_mysql_config()
    table = cfg["table"]
    charset = cfg["charset"]
    try:
        # 1. 建库
        conn = _connect(include_db=False)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` "
                    f"DEFAULT CHARACTER SET {charset} COLLATE {charset}_general_ci"
                )
            conn.commit()
        finally:
            conn.close()

        # 2. 建表
        conn = _connect(include_db=True)
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS `{table}` (
                        `file_sn`     VARCHAR(32)  NOT NULL COMMENT '文件编号(一个文件一个)',
                        `data_sn`     INT          NOT NULL DEFAULT 1 COMMENT '数据顺序号(文件内1,2,3...)',
                        `file_name`   VARCHAR(512) DEFAULT NULL COMMENT '文件名',
                        `model`       VARCHAR(100) DEFAULT NULL COMMENT '型号',
                        `spec`        VARCHAR(100) DEFAULT NULL COMMENT '规格',
                        `voltage`     VARCHAR(100) DEFAULT NULL COMMENT '电压',
                        `color`       VARCHAR(100) DEFAULT NULL COMMENT '颜色',
                        `standard`    VARCHAR(100) DEFAULT NULL COMMENT '标准',
                        `quantity`    DECIMAL(18,3) DEFAULT NULL COMMENT '数量',
                        `unit`        VARCHAR(100) DEFAULT NULL COMMENT '单位',
                        `create_date` DATETIME     NOT NULL COMMENT '建立日期',
                        `edit_date`   DATETIME     NOT NULL COMMENT '修改日期',
                        `staff_id`    VARCHAR(50)  DEFAULT NULL COMMENT '工号',
                        PRIMARY KEY (`file_sn`, `data_sn`)
                    ) ENGINE=InnoDB DEFAULT CHARSET={charset} COMMENT='物料文件分析结果'
                """)
                conn.commit()

                # 旧表迁移：补 data_sn / file_name 列，并将单列 PK 改为联合 PK
                if not _table_has_column(cur, table, "data_sn"):
                    cur.execute(
                        f"ALTER TABLE `{table}` ADD COLUMN `data_sn` "
                        f"INT NOT NULL DEFAULT 1 COMMENT '数据顺序号(文件内1,2,3...)'"
                    )
                if not _table_has_column(cur, table, "file_name"):
                    cur.execute(
                        f"ALTER TABLE `{table}` ADD COLUMN `file_name` "
                        f"VARCHAR(512) DEFAULT NULL COMMENT '文件名'"
                    )
                pk = _table_pk_cols(cur, table)
                if "data_sn" not in pk:
                    try:
                        cur.execute(f"ALTER TABLE `{table}` DROP PRIMARY KEY, "
                                    f"ADD PRIMARY KEY (`file_sn`, `data_sn`)")
                    except Exception as e:
                        if logger:
                            logger(f"MySQL PK 迁移跳过(可能已有重复): {e}")
                conn.commit()
        finally:
            conn.close()
        if logger:
            logger(f"MySQL 库表就绪: {cfg['database']}.{table}")
        return True
    except Exception as e:
        if logger:
            logger(f"MySQL 初始化失败: {e}")
        return False


def save_material_items(items: List[Dict[str, Any]], staff_id: str = "",
                        logger=None, file_sn: Optional[str] = None,
                        data_sns: Optional[List[int]] = None,
                        file_name: Optional[str] = None) -> Dict[str, Any]:
    """
    将物料条目批量保存到 material_analysis。
    一个文件的所有条目共用同一个 file_sn，每条用 data_sn(1,2,3...) 区分。
    items: 中文字段名 dict 列表（型号/规格/电压/颜色/标准/数量/单位）
    staff_id: 客户端传入的工号
    file_sn: 文件编号（一个文件一个），为空则自动生成
    data_sns: 数据顺序号列表，与 items 按下标对应；为空则按 1,2,3... 生成
    file_name: 分析的文件名
    返回: {"saved": int, "file_sn": str, "data_sns": [int], "error": str|None}
    """
    cfg = get_mysql_config()
    if not cfg["enabled"]:
        return {"saved": 0, "file_sn": file_sn or "", "data_sns": data_sns or [],
                "error": None, "skipped": "mysql_disabled"}
    if not items:
        return {"saved": 0, "file_sn": file_sn or "", "data_sns": data_sns or [],
                "error": None}

    if not init_db(logger=logger):
        return {"saved": 0, "file_sn": file_sn or "", "data_sns": data_sns or [],
                "error": "MySQL 不可用，库表初始化失败"}

    table = cfg["table"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f_sn = str(file_sn).strip() if file_sn and str(file_sn).strip() else generate_file_sn()
    rows, d_sns_out = [], []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        d_sn = int(data_sns[idx]) if (
            data_sns and idx < len(data_sns) and data_sns[idx]
        ) else idx + 1
        d_sns_out.append(d_sn)
        rows.append((
            f_sn, d_sn,
            (file_name or None),
            (it.get("型号") or None),
            (it.get("规格") or None),
            (it.get("电压") or None),
            (it.get("颜色") or None),
            (it.get("标准") or None),
            _to_number(it.get("数量")),
            (it.get("单位") or None),
            now, now,
            (staff_id or None),
        ))

    if not rows:
        return {"saved": 0, "file_sn": f_sn, "data_sns": d_sns_out, "error": None}

    sql = (
        f"INSERT INTO `{table}` "
        f"(file_sn, data_sn, file_name, model, spec, voltage, color, standard, "
        f"quantity, unit, create_date, edit_date, staff_id) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    try:
        conn = _connect(include_db=True)
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            conn.commit()
        finally:
            conn.close()
        if logger:
            logger(f"MySQL 已保存 {len(rows)} 条物料记录，file_sn={f_sn}，工号={staff_id or '(空)'}")
        return {"saved": len(rows), "file_sn": f_sn, "data_sns": d_sns_out, "error": None}
    except Exception as e:
        return {"saved": 0, "file_sn": f_sn, "data_sns": d_sns_out, "error": str(e)}
