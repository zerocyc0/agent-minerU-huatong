# encoding: utf-8
# @file: db.py
import configparser, json, os, threading
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import pymysql
    import pymysql.cursors
    MySQLError = pymysql.MySQLError
except ImportError:
    pymysql = None
    class MySQLError(Exception): pass

try:
    from werkzeug.security import generate_password_hash, check_password_hash
except ImportError:
    import hashlib as _hl
    _SALT = "huatong-mineru-web-pwd-salt-2026"
    def generate_password_hash(p: str) -> str:
        return _hl.sha256(f"{_SALT}|{p}".encode()).hexdigest()
    def check_password_hash(h: str, p: str) -> bool:
        return h == generate_password_hash(p)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(_BASE_DIR, "config.ini"), encoding="utf-8")

def _cfg_mysql(section="mysql") -> Dict[str, Any]:
    cfg = dict(
        host=_cfg.get(section,"host",fallback="127.0.0.1"),
        port=_cfg.getint(section,"port",fallback=3306),
        user=_cfg.get(section,"user",fallback="root"),
        password=_cfg.get(section,"password",fallback=""),
        database=_cfg.get(section,"database",fallback="huatong"),
        charset=_cfg.get(section,"charset",fallback="utf8mb4"),
        autocommit=True,
        connect_timeout=5,
    )
    if pymysql is not None:
        cfg["cursorclass"] = pymysql.cursors.DictCursor
    return cfg

_conn_lock = threading.Lock()
_conn = None

def _get_conn():
    global _conn
    with _conn_lock:
        if pymysql is None:
            raise RuntimeError("missing pymysql")
        need_new = _conn is None
        if not need_new:
            try:
                with _conn.cursor() as tc: tc.execute("SELECT 1")
            except Exception:
                need_new = True
        if need_new:
            try:
                _conn = pymysql.connect(**_cfg_mysql())
            except MySQLError as e:
                _conn = None
                raise
        return _conn

def _cursor(dictionary=True):
    c = _get_conn()
    return c.cursor() if dictionary else c.cursor(pymysql.cursors.Cursor)

def _table_columns(table: str) -> List[str]:
    cur = _cursor()
    try:
        cur.execute(f"DESCRIBE `{table}`")
        return [str(r["Field"]) for r in cur.fetchall()]
    finally:
        try: cur.close()
        except Exception: pass

QUERY_TABLES = ("material_analysis", "material_analysis_last")

def _row_to_user(row):
    if not row: return None
    out = dict(
        staff_id=row.get("staff_id"),
        username=row.get("username"),
        real_name=row.get("real_name") or "",
        role=row.get("role") or "employee",
        status=bool(row.get("status")) if row.get("status") is not None else True,
        perm_analysis=bool(row.get("perm_analysis")) if row.get("perm_analysis") is not None else False,
        perm_query=bool(row.get("perm_query")) if row.get("perm_query") is not None else False,
        create_date=row.get("create_date"),
        update_date=row.get("edit_date") or row.get("update_date"),
        last_login=row.get("last_login") or row.get("edit_date"),
    )
    for k in ("create_date","update_date","last_login"):
        if isinstance(out[k], datetime):
            out[k] = out[k].strftime("%Y-%m-%d %H:%M:%S")
    return out

def get_user_by_staff_id(staff_id: str):
    if not staff_id: return None
    try:
        cur = _cursor()
        try:
            cur.execute("SELECT * FROM users WHERE staff_id=%s LIMIT 1", (str(staff_id),))
            return _row_to_user(cur.fetchone())
        finally:
            try: cur.close()
            except Exception: pass
    except Exception:
        return None

def get_user_by_username(username: str):
    if not username: return None
    try:
        cur = _cursor()
        try:
            cur.execute("SELECT * FROM users WHERE username=%s LIMIT 1", (str(username),))
            return _row_to_user(cur.fetchone())
        finally:
            try: cur.close()
            except Exception: pass
    except Exception:
        return None

def list_users():
    try:
        cur = _cursor()
        try:
            cur.execute("SELECT * FROM users ORDER BY create_date DESC")
            return [_row_to_user(r) for r in cur.fetchall()]
        finally:
            try: cur.close()
            except Exception: pass
    except Exception:
        return []

def verify_login(username: str, password: str):
    if not username or not password: return None
    cur = _cursor()
    try:
        cur.execute("SELECT * FROM users WHERE username=%s LIMIT 1", (username,))
        row = cur.fetchone()
        if not row: return None
        if not bool(row.get("status", 1)):
            raise PermissionError("账号已被禁用，请联系管理员")
        stored = row.get("password_hash") or row.get("password") or ""
        if not check_password_hash(stored, password):
            return None
        sid = row["staff_id"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cols = _table_columns("users")
        if "last_login" in cols:
            cur.execute("UPDATE users SET last_login=%s WHERE staff_id=%s", (now, sid))
        else:
            cur.execute("UPDATE users SET edit_date=%s WHERE staff_id=%s", (now, sid))
        row2 = dict(row); row2["last_login"] = now
        return _row_to_user(row2)
    finally:
        try: cur.close()
        except Exception: pass

def create_user(staff_id, username, password, real_name="", role="employee",
                perm_analysis=True, perm_query=True):
    if not password or len(password) < 6: raise ValueError("密码至少 6 位")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pw = generate_password_hash(password)
    cols = _table_columns("users")
    ed_col = "edit_date" if "edit_date" in cols else "update_date"
    ins_cols = ["staff_id","username","password_hash","real_name","role","status",
                "perm_analysis","perm_query","create_date", ed_col]
    vals = [staff_id, username, pw, real_name, role, 1,
            1 if perm_analysis else 0, 1 if perm_query else 0, now, now]
    cur = _cursor()
    try:
        col_sql = ", ".join(f"`{c}`" for c in ins_cols)
        cur.execute(f"INSERT INTO users ({col_sql}) VALUES ({', '.join(['%s']*len(ins_cols))})", vals)
    finally:
        try: cur.close()
        except Exception: pass
    return get_user_by_staff_id(staff_id)

def update_user(staff_id: str, data: Dict[str, Any]):
    if not data: return get_user_by_staff_id(staff_id)
    sets, vals = [], []
    for k, v in data.items():
        if k == "password":
            sets.append("`password_hash`=%s")
            vals.append(generate_password_hash(str(v)))
        elif k in ("status","perm_analysis","perm_query"):
            sets.append(f"`{k}`=%s"); vals.append(1 if bool(v) else 0)
        elif k in ("real_name","role","username"):
            sets.append(f"`{k}`=%s"); vals.append(v)
    if not sets: return get_user_by_staff_id(staff_id)
    sets.append("`edit_date`=%s"); vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    vals.append(staff_id)
    cur = _cursor()
    try:
        cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE staff_id=%s", vals)
    finally:
        try: cur.close()
        except Exception: pass
    return get_user_by_staff_id(staff_id)

def delete_user(staff_id: str) -> bool:
    cur = _cursor()
    try:
        cur.execute("DELETE FROM users WHERE staff_id=%s", (staff_id,))
        return True
    finally:
        try: cur.close()
        except Exception: pass

_KNOWN_MATERIAL = {"file_sn","data_sn","model","spec","voltage","color","standard",
                   "quantity","unit","create_date","edit_date","staff_id","file_name",
                   "row_index"}

def _ensure_col(table: str, col: str, dtype="VARCHAR(1024) NULL"):
    cur = _cursor()
    try:
        cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (col,))
        if cur.fetchone(): return
        cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col.replace('`','')}` {dtype}")
    except Exception:
        pass
    finally:
        try: cur.close()
        except Exception: pass

def _qty(v):
    if v is None or v == "": return None
    try: return float(v)
    except (TypeError, ValueError): return v

def save_analysis_rows(rows, staff_id: str, logger=None):
    """保存物料行到 material_analysis_last。
    用 (file_sn, data_sn) 联合键标识每行，写入 modify=1 标记已保存。
    每条行根据 (file_sn, data_sn) 是否存在 + modified 标志分三类处理：
      1. (file_sn, data_sn) 不存在（首次保存）→ INSERT，modify=1；
      2. (file_sn, data_sn) 已存在 且 modified=True（用户编辑过）→ UPDATE 非键列，modify=1；
      3. (file_sn, data_sn) 已存在 且 modified=False → 跳过（已保存过，无需重复保存）。
    返回 dict: {"saved","inserted","updated","skipped","errors":[],
                "file_sns":[str,...], "data_sns":[int,...]}
    """
    inserted, updated, skipped = 0, 0, 0
    errors, file_sns_out, data_sns_out = [], [], []
    now = datetime.now()
    today = now.strftime("%Y-%m-%d %H:%M:%S")
    base_prefix = "MA" + now.strftime("%Y%m%d%H%M%S")
    _seq_counter = [0]
    _dseq_counter = [0]

    def _next_sn(cursor):
        while True:
            sn = "%s%03d" % (base_prefix, _seq_counter[0])
            _seq_counter[0] += 1
            cursor.execute("SELECT file_sn FROM `material_analysis_last` WHERE `file_sn`=%s LIMIT 1", (sn,))
            if not cursor.fetchone():
                return sn

    def _next_dsn(cursor, f_sn):
        _dseq_counter[0] = 0
        while True:
            _dseq_counter[0] += 1
            d = _dseq_counter[0]
            cursor.execute("SELECT data_sn FROM `material_analysis_last` WHERE `file_sn`=%s AND `data_sn`=%s LIMIT 1", (f_sn, d))
            if not cursor.fetchone():
                return d

    sid = (staff_id or "").strip() or None
    cur = _cursor()
    try:
        cols = set(_table_columns("material_analysis_last"))
        for idx, r in enumerate(rows):
            try:
                if not isinstance(r, dict):
                    errors.append("第 %d 行不是对象，跳过" % idx)
                    file_sns_out.append("")
                    data_sns_out.append(0)
                    continue
                row = dict(r)
                modified_flag = bool(row.get("modified"))
                raw_sn = str(row.get("file_sn") or "").strip()
                raw_dsn = row.get("data_sn")
                try:
                    raw_dsn = int(raw_dsn) if raw_dsn is not None and str(raw_dsn).strip() else None
                except (TypeError, ValueError):
                    raw_dsn = None

                # --- 分支 2/3：(file_sn, data_sn) 已存在 ---
                if raw_sn and raw_dsn is not None:
                    cur.execute("SELECT file_sn FROM `material_analysis_last` WHERE `file_sn`=%s AND `data_sn`=%s LIMIT 1", (raw_sn, raw_dsn))
                    exists = cur.fetchone()
                    if not exists:
                        wc, wp, wv = [], [], []
                        def _put(c, v, d="VARCHAR(1024) NULL"):
                            nonlocal wc, wp, wv, cols
                            if c not in cols: _ensure_col("material_analysis_last", c, d); cols.add(c)
                            wc.append("`%s`" % c); wp.append("%s"); wv.append(v)
                        _put("file_sn", raw_sn, "VARCHAR(64)")
                        _put("data_sn", raw_dsn, "INT DEFAULT 1")
                        _put("staff_id", sid)
                        if row.get("file_name"): _put("file_name", str(row["file_name"]), "VARCHAR(512)")
                        _put("row_index", idx, "INT DEFAULT 0")
                        for col in ("model","spec","voltage","color","standard","unit"):
                            if col in row and row[col] not in (None, ""):
                                _put(col, str(row[col]), "VARCHAR(255) NULL")
                        q = _qty(row.get("quantity"))
                        if q is not None: _put("quantity", q, "DECIMAL(18,3) NULL")
                        _put("create_date", today, "DATETIME NULL")
                        _put("edit_date", today, "DATETIME NULL")
                        _put_extra(row, cols, wc, wp, wv)
                        cur.execute("INSERT INTO `material_analysis_last` (%s) VALUES (%s)" %
                                    (", ".join(wc), ", ".join(wp)), wv)
                        inserted += 1
                        file_sns_out.append(raw_sn)
                        data_sns_out.append(raw_dsn)
                        continue
                    if modified_flag:
                        sets, vals, cols_used = [], [], set()
                        def _set(c, v, d="VARCHAR(1024) NULL"):
                            nonlocal sets, vals, cols, cols_used
                            if c not in cols: _ensure_col("material_analysis_last", c, d); cols.add(c)
                            cols_used.add(c); sets.append("`%s`=%%s" % c); vals.append(v)
                        if row.get("file_name"): _set("file_name", str(row["file_name"]), "VARCHAR(512)")
                        for col in ("model","spec","voltage","color","standard","unit"):
                            if col in row and row[col] not in (None, ""):
                                _set(col, str(row[col]), "VARCHAR(255) NULL")
                        q = _qty(row.get("quantity"))
                        if q is not None: _set("quantity", q, "DECIMAL(18,3) NULL")
                        _set("edit_date", today, "DATETIME NULL")
                        if sid is not None: _set("staff_id", sid)
                        _extra_updates(row, cols, sets, vals, cols_used)
                        if sets:
                            vals.extend([raw_sn, raw_dsn])
                            cur.execute("UPDATE `material_analysis_last` SET %s WHERE `file_sn`=%%s AND `data_sn`=%%s" %
                                        ", ".join(sets), vals)
                        updated += 1
                        file_sns_out.append(raw_sn)
                        data_sns_out.append(raw_dsn)
                    else:
                        skipped += 1
                        file_sns_out.append(raw_sn)
                        data_sns_out.append(raw_dsn)
                    continue

                # --- 分支 1：file_sn 或 data_sn 为空 → INSERT 并生成新编号 ---
                wc, wp, wv = [], [], []
                file_sn = raw_sn or _next_sn(cur)
                data_sn = raw_dsn or _next_dsn(cur, file_sn)
                def _put(c, v, d="VARCHAR(1024) NULL"):
                    nonlocal wc, wp, wv, cols
                    if c not in cols: _ensure_col("material_analysis_last", c, d); cols.add(c)
                    wc.append("`%s`" % c); wp.append("%s"); wv.append(v)
                _put("staff_id", sid)
                _put("file_sn", file_sn, "VARCHAR(64)")
                _put("data_sn", data_sn, "INT DEFAULT 1")
                if row.get("file_name"): _put("file_name", str(row["file_name"]), "VARCHAR(512)")
                _put("row_index", idx, "INT DEFAULT 0")
                for col in ("model","spec","voltage","color","standard","unit"):
                    if col in row and row[col] not in (None, ""):
                        _put(col, str(row[col]), "VARCHAR(255) NULL")
                q = _qty(row.get("quantity"))
                if q is not None: _put("quantity", q, "DECIMAL(18,3) NULL")
                _put("create_date", today, "DATETIME NULL")
                _put("edit_date", today, "DATETIME NULL")
                _put_extra(row, cols, wc, wp, wv)
                sql = "INSERT INTO `material_analysis_last` (%s) VALUES (%s)" % (", ".join(wc), ", ".join(wp))
                cur.execute(sql, wv)
                inserted += 1
                file_sns_out.append(file_sn)
                data_sns_out.append(data_sn)
            except Exception as e:
                errors.append("第 %d 行失败: %s" % (idx, e))
                file_sns_out.append("")
                data_sns_out.append(0)
    except Exception as e:
        errors.append("数据库操作失败: %s" % e)
    finally:
        try: cur.close()
        except Exception: pass
    saved = inserted + updated
    if logger:
        logger("[DB] save_analysis_rows 新增 %d 条，更新 %d 条，已保存跳过 %d 条，失败 %d 条 (工号=%s)"
               % (inserted, updated, skipped, len(errors), staff_id))
    out = {
        "saved": saved, "inserted": inserted, "updated": updated,
        "skipped": skipped, "errors": errors,
        "file_sns": file_sns_out, "data_sns": data_sns_out,
    }
    return out


def _put_extra(row, cols, wc, wp, wv):
    """INSERT 时把已知列之外的标量列/复杂 JSON 动态写入。"""
    for k, v in row.items():
        if k in _KNOWN_MATERIAL or k in ("staff_id","file_sn","data_sn","file_name","row_index",
            "model","spec","voltage","color","standard","quantity","unit",
            "create_date","edit_date","modified","id"): continue
        if isinstance(v, (dict, list)):
            wc.append("`row_json`"); wp.append("%s"); wv.append(json.dumps(row, ensure_ascii=False))
            cols.add("row_json")
            continue
        if v is None or v == "": continue
        if isinstance(v, bool):
            wc.append("`%s`" % k); wp.append("%s"); wv.append(1 if v else 0)
            cols.add(k)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            wc.append("`%s`" % k); wp.append("%s"); wv.append(v)
            cols.add(k)
        else:
            s = str(v)
            dtype = "VARCHAR(1024) NULL" if len(s) <= 1024 else "MEDIUMTEXT NULL"
            # _ensure_col only adds if missing (but cols set may be stale); always write col
            wc.append("`%s`" % k); wp.append("%s"); wv.append(s)
            cols.add(k)


def _extra_updates(row, cols, sets, vals, cols_used):
    """UPDATE 时处理已知列外的标量/JSON 动态列，保证编辑保存也能写进自定义列。"""
    for k, v in row.items():
        if k in _KNOWN_MATERIAL or k in ("staff_id","file_sn","data_sn","file_name","row_index",
            "model","spec","voltage","color","standard","quantity","unit",
            "create_date","edit_date","modified","id"): continue
        if k in cols_used: continue
        if isinstance(v, (dict, list)):
            # UPDATE row_json 用 INSERT-style full row JSON 记录
            cols_used.add(k)
            if "row_json" not in cols:
                _ensure_col("material_analysis_last", "row_json", "JSON")
                cols.add("row_json")
            sets.append("`row_json`=%s")
            vals.append(json.dumps(row, ensure_ascii=False))
            cols_used.add("row_json")
            continue
        if isinstance(v, bool):
            sets.append("`%s`=%%s" % k); vals.append(1 if v else 0)
            cols_used.add(k)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            sets.append("`%s`=%%s" % k); vals.append(v)
            cols_used.add(k)
        elif v is not None and str(v) != "":
            s = str(v)
            sets.append("`%s`=%%s" % k); vals.append(s)
            cols_used.add(k)

def query_materials(start, end, table="material_analysis", staff_filter=None):
    if table not in QUERY_TABLES: raise ValueError(f"不支持的数据表: {table}")
    sql = f"SELECT * FROM `{table}` WHERE DATE(create_date) BETWEEN %s AND %s"
    vals = [start, end]
    if staff_filter:
        sql += " AND staff_id=%s"; vals.append(staff_filter)
    sql += " ORDER BY create_date DESC LIMIT 5000"
    cur = _cursor()
    try:
        cur.execute(sql, vals); raw = cur.fetchall()
    finally:
        try: cur.close()
        except Exception: pass
    out = []
    for r in raw:
        d = {k: (v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v)
             for k, v in r.items()}
        if d.get("row_json"):
            try:
                j = json.loads(d["row_json"]) if isinstance(d["row_json"], str) else d["row_json"]
                if isinstance(j, dict):
                    for k, v in j.items():
                        if k not in d or d[k] is None or d[k] == "": d[k] = v
            except Exception: pass
        out.append(d)
    return out

def build_chart(rows, start, end):
    """返回前端 renderChart 需要的桶数组: [{"label": str, "count": int}, ...]
    - 当日查询(start==end): 按 0~23 小时分桶，label 如 "08时"
    - 跨天查询: 按日期分桶，label 为 "MM-DD"
    rows 中的 create_date 已由 query_materials 归一化为 "YYYY-MM-DD HH:MM:SS" 字符串。
    """
    from collections import OrderedDict
    from datetime import timedelta
    try:
        sd = datetime.strptime(start, "%Y-%m-%d").date()
        ed = datetime.strptime(end, "%Y-%m-%d").date()
    except Exception:
        return [{"label": "", "count": len(rows)}]

    if sd == ed:
        # 当日：24 个小时桶
        counts = {h: 0 for h in range(24)}
        for r in rows:
            cd = str(r.get("create_date") or "")
            if len(cd) >= 13:
                try:
                    counts[int(cd[11:13])] += 1
                except (ValueError, TypeError):
                    pass
        return [{"label": f"{h:02d}时", "count": counts[h]} for h in range(24)]

    # 跨天：日期桶
    daily = OrderedDict()
    d = sd
    while d <= ed:
        daily[d.isoformat()] = 0
        d += timedelta(days=1)
    for r in rows:
        cd = str(r.get("create_date") or "")
        if len(cd) >= 10:
            key = cd[:10]
            if key in daily:
                daily[key] += 1
    return [{"label": k[5:], "count": v} for k, v in daily.items()]

def init_db(logger=None) -> bool:
    try:
        if pymysql is None: raise RuntimeError("missing pymysql")
        m_root = _cfg_mysql()
        dbname = m_root.pop("database")
        conn0 = pymysql.connect(**m_root)
        cur0 = conn0.cursor()
        try:
            cur0.execute(f"CREATE DATABASE IF NOT EXISTS `{dbname}` "
                         f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cur0.execute(f"USE `{dbname}`")
        finally:
            try: cur0.close()
            except Exception: pass
            try: conn0.close()
            except Exception: pass
        global _conn
        with _conn_lock:
            try:
                if _conn: _conn.close()
            except Exception: pass
            _conn = None
        conn = _get_conn()
        cur = conn.cursor()
        try:
            try:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        staff_id VARCHAR(50) NOT NULL PRIMARY KEY,
                        username VARCHAR(50) NOT NULL UNIQUE KEY,
                        password_hash VARCHAR(255) NOT NULL,
                        real_name VARCHAR(100) DEFAULT '',
                        role VARCHAR(20) NOT NULL DEFAULT 'employee',
                        perm_analysis TINYINT(1) NOT NULL DEFAULT 0,
                        perm_query TINYINT(1) NOT NULL DEFAULT 0,
                        `status` TINYINT(1) NOT NULL DEFAULT 1,
                        create_date DATETIME NOT NULL,
                        edit_date DATETIME NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            except Exception: pass
            try:
                user_cols = set(_table_columns("users"))
                if "last_login" not in user_cols:
                    cur.execute("ALTER TABLE users ADD COLUMN last_login DATETIME NULL")
            except Exception: pass
            for tbl in ("material_analysis_last", "material_analysis"):
                try:
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS `{tbl}` (
                            file_sn VARCHAR(32),
                            data_sn INT DEFAULT 1,
                            file_name VARCHAR(512),
                            model VARCHAR(100), spec VARCHAR(100),
                            voltage VARCHAR(100), color VARCHAR(100), standard VARCHAR(100),
                            quantity DECIMAL(18,3), unit VARCHAR(100),
                            create_date DATETIME, edit_date DATETIME, staff_id VARCHAR(50),
                            INDEX idx_staff_date (staff_id, create_date),
                            INDEX idx_file_sn (file_sn)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
                except Exception: pass
                # 旧表迁移：补缺失列
                for col, dtype in (("data_sn","INT DEFAULT 1"),
                                   ("file_name","VARCHAR(512)")):
                    try:
                        cur.execute(f"SHOW COLUMNS FROM `{tbl}` LIKE %s", (col,))
                        if not cur.fetchone():
                            cur.execute(f"ALTER TABLE `{tbl}` ADD COLUMN `{col}` {dtype}")
                    except Exception: pass
            admin = get_user_by_staff_id("admin")
            if not admin:
                create_user("admin", "admin", "admin123", real_name="系统内置管理员",
                            role="admin", perm_analysis=True, perm_query=True)
                if logger: logger("[DB] 初始化 - 创建内置管理员 admin / admin123")
        finally:
            try: cur.close()
            except Exception: pass
        if logger: logger("[DB] 初始化完成")
        return True
    except Exception as e:
        if logger: logger(f"[DB] 初始化失败: {e}")
        return False
