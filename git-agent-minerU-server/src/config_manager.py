# encoding: utf-8
# @file: config_manager.py
# @desc: config.ini 配置管理，首次运行自动创建并写入默认配置
import os
import time
import configparser

# config.ini 与本文件同目录（src/）
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_SRC_DIR, "config.ini")

# 默认配置
_DEFAULT_CONFIG = {
    "file_storage": {
        # 客户端上传文件保存目录（相对路径基于 src/ 解析）
        "save_dir": os.path.join(_SRC_DIR, "received_files"),
        # 单文件最大字节数（默认 100MB）
        "max_file_size": "104857600",
        # 是否允许同名文件覆盖（no=追加时间戳后缀）
        "overwrite": "no",
    },
    "mineru": {
        # 是否启用 MinerU 高精度解析（不可用时自动降级到传统解析器）
        "enabled": "yes",
        # 解析后端：pipeline(CPU兼容) / vlm-engine(GPU高精度) / hybrid-engine(混合)
        "backend": "pipeline",
        # mineru-api 服务地址
        "api_url": "http://127.0.0.1:8888",
        # mineru-api 不可用时是否自动启动（需已安装 mineru 并在 PATH 中可执行 mineru-api）
        "auto_start": "yes",
        # MinerU 输出临时目录
        "work_dir": os.path.join(_SRC_DIR, "mineru_output"),
    },
    "server": {
        # WebSocket 监听地址与端口
        "host": "0.0.0.0",
        "port": "8765",
    },
    "mysql": {
        # 是否启用 MySQL 保存解析结果（no=仅返回不写库）
        "enabled": "yes",
        "host": "127.0.0.1",
        "port": "3306",
        "user": "root",
        "password": "123456",
        "database": "huatong",
        "table": "material_analysis",
        "charset": "utf8mb4",
    },
}

_config_cache = None


def _fill_defaults(config: configparser.ConfigParser) -> bool:
    """补齐缺失的 section / option，返回是否有变更"""
    changed = False
    for section, items in _DEFAULT_CONFIG.items():
        if section not in config:
            config[section] = {}
            changed = True
        for k, v in items.items():
            if k not in config[section]:
                config[section][k] = v
                changed = True
    return changed


def get_config() -> configparser.ConfigParser:
    """读取 config.ini；不存在则自动创建并写入默认配置；存在但配置项不全则补齐。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config = configparser.ConfigParser()

    if not os.path.exists(CONFIG_PATH):
        _fill_defaults(config)
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            config.write(f)
    else:
        config.read(CONFIG_PATH, encoding="utf-8")
        if _fill_defaults(config):
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                config.write(f)

    _config_cache = config
    return config


def get_save_dir() -> str:
    """获取文件保存目录（绝对路径），不存在则创建"""
    config = get_config()
    save_dir = config.get(
        "file_storage", "save_dir",
        fallback=_DEFAULT_CONFIG["file_storage"]["save_dir"]
    )
    if not os.path.isabs(save_dir):
        save_dir = os.path.join(_SRC_DIR, save_dir)
    os.makedirs(save_dir, exist_ok=True)
    return save_dir


def get_max_file_size() -> int:
    """获取单文件最大字节数"""
    config = get_config()
    try:
        return config.getint(
            "file_storage", "max_file_size", fallback=104857600
        )
    except ValueError:
        return 104857600


def is_overwrite_enabled() -> bool:
    """是否允许同名文件覆盖"""
    config = get_config()
    return config.getboolean("file_storage", "overwrite", fallback=False)


def build_save_path(file_name: str) -> str:
    """
    根据客户端发送的文件名，在保存目录下构造安全保存路径：
    - 仅取 basename，防止路径遍历
    - overwrite=no 时，同名文件追加时间戳后缀
    """
    save_dir = get_save_dir()
    safe_name = os.path.basename(file_name) or "unnamed"
    save_path = os.path.join(save_dir, safe_name)

    if not is_overwrite_enabled() and os.path.exists(save_path):
        ts = time.strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(safe_name)
        save_path = os.path.join(save_dir, f"{name}_{ts}{ext}")

    return save_path


def get_mineru_config() -> dict:
    """获取 MinerU 相关配置"""
    config = get_config()
    d = _DEFAULT_CONFIG["mineru"]
    return {
        "enabled": config.getboolean("mineru", "enabled", fallback=True),
        "backend": config.get("mineru", "backend", fallback=d["backend"]),
        "api_url": config.get("mineru", "api_url", fallback=d["api_url"]),
        "auto_start": config.getboolean("mineru", "auto_start", fallback=True),
        "work_dir": config.get("mineru", "work_dir", fallback=d["work_dir"]),
    }


def get_server_config() -> dict:
    """获取 WebSocket 服务配置"""
    config = get_config()
    return {
        "host": config.get("server", "host", fallback="0.0.0.0"),
        "port": config.getint("server", "port", fallback=8765),
    }


def get_mysql_config() -> dict:
    """获取 MySQL 数据库配置"""
    config = get_config()
    d = _DEFAULT_CONFIG["mysql"]
    return {
        "enabled": config.getboolean("mysql", "enabled", fallback=True),
        "host": config.get("mysql", "host", fallback=d["host"]),
        "port": config.getint("mysql", "port", fallback=3306),
        "user": config.get("mysql", "user", fallback=d["user"]),
        "password": config.get("mysql", "password", fallback=d["password"]),
        "database": config.get("mysql", "database", fallback=d["database"]),
        "table": config.get("mysql", "table", fallback=d["table"]),
        "charset": config.get("mysql", "charset", fallback=d["charset"]),
    }
