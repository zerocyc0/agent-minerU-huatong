# encoding: utf-8
# @file: mineru_client.py
# @desc: 本地 MinerU 解析客户端。优先连接已运行的 mineru-api，不可用时自动启动；
#        通过 HTTP /file_parse 接口获取高质量 Markdown，供后续 LLM 字段提取使用。
import os
import time
import subprocess
import threading
from urllib.parse import urlparse

import requests


class MinerUClient:
    """
    本地 MinerU 解析客户端（单例）。
    - ensure_started(): 探测 mineru-api /health，不可用则自动启动 mineru-api 子进程
    - parse_to_markdown(file_path): 调用 /file_parse 解析单文件，返回 Markdown 文本
    - MinerU 不可用时抛 RuntimeError，由调用方降级到传统解析器
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self, api_url, auto_start=True, backend="auto", work_dir=None, logger=None):
        self.api_url = (api_url or "http://127.0.0.1:8888").rstrip("/")
        self.auto_start = auto_start
        self.backend = backend
        self.work_dir = work_dir or os.path.join(os.getcwd(), "mineru_output")
        self.logger = logger or (lambda msg: None)
        self._proc = None
        self._start_lock = threading.Lock()
        self._tried_start = False

    @classmethod
    def get_instance(cls, logger=None):
        """获取单例（从 config_manager 读取配置）"""
        with cls._lock:
            if cls._instance is None:
                from config_manager import get_mineru_config
                cfg = get_mineru_config()
                cls._instance = cls(
                    cfg["api_url"], cfg["auto_start"], cfg["backend"],
                    cfg["work_dir"], logger
                )
            elif logger is not None:
                cls._instance.logger = logger
            return cls._instance

    @staticmethod
    def resolve_executable() -> str:
        """
        解析 mineru-api 可执行文件路径：
        - 优先 PATH 中的 mineru-api
        - 否则在当前 Python 解释器同目录（venv Scripts/）下查找
        返回可执行文件路径字符串；找不到返回 None。
        """
        from shutil import which
        exe = which("mineru-api")
        if exe:
            return exe
        # venv 未激活时，从 sys.executable 同目录查找
        import sys
        scripts_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(scripts_dir, "mineru-api" + (".exe" if os.name == "nt" else ""))
        if os.path.exists(candidate):
            return candidate
        # 兼容部分版本命令名为 mineru
        candidate2 = os.path.join(scripts_dir, "mineru" + (".exe" if os.name == "nt" else ""))
        if os.path.exists(candidate2):
            return candidate2
        return None

    @staticmethod
    def is_installed() -> bool:
        """检查 mineru 是否已安装（以能否导入入口模块为准，比检测 exe 包装器更可靠）"""
        try:
            import importlib.util
            return importlib.util.find_spec("mineru.cli.fast_api") is not None
        except Exception:
            return MinerUClient.resolve_executable() is not None

    def is_available(self) -> bool:
        """探测 mineru-api 是否健康"""
        try:
            r = requests.get(f"{self.api_url}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def ensure_started(self) -> bool:
        """确保 mineru-api 已启动并健康；不可用且允许自启则启动子进程"""
        if self.is_available():
            return True
        if not self.auto_start:
            return False
        with self._start_lock:
            if self.is_available():
                return True
            if self._tried_start:
                return False
            self._tried_start = True

            if not self.is_installed():
                self.logger("未找到 mineru，请先安装（pip install \"mineru[core]\"）")
                return False

            import sys
            parsed = urlparse(self.api_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8888
            os.makedirs(self.work_dir, exist_ok=True)

            env = os.environ.copy()
            # 限制 BLAS/OMP 线程数，避免 Windows 内存受限时
            # OpenBLAS 为多线程预分配内存失败（Memory allocation failed）
            for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                       "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
                env.setdefault(_v, "1")
            # 国内优先从 modelscope 拉取模型，避免 huggingface 网络问题
            env.setdefault("MINERU_MODEL_SOURCE", "modelscope")
            # 指定项目本地 mineru.json 配置路径，避免写入 C:\Users\<user>\ 时权限不足
            _cfg_json = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "mineru.json",
            )
            if os.path.exists(_cfg_json):
                env["MINERU_TOOLS_CONFIG_JSON"] = _cfg_json

            # 用当前 venv 的 python.exe 直接调用入口模块（mineru.cli.fast_api:main），
            # 比 mineru-api.exe 包装器更可靠（部分 Windows 环境下 exe 包装器会卡住/被拦截）。
            cmd = [
                sys.executable, "-c",
                "from mineru.cli.fast_api import main; main()",
                "--host", host, "--port", str(port),
            ]
            self.logger(f"正在启动 mineru-api（{host}:{port}）...")
            try:
                # 子进程日志写入 work_dir/mineru_api.log，便于启动失败时排查
                self._log_path = os.path.join(self.work_dir, "mineru_api.log")
                self._log_fp = open(self._log_path, "ab")
                kwargs = dict(
                    stdout=self._log_fp,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=self.work_dir,
                )
                if os.name == "nt":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                self._proc = subprocess.Popen(cmd, **kwargs)
            except Exception as e:
                self.logger(f"启动 mineru-api 失败: {e}")
                return False

            # 等待健康（首次加载模型可能需要较长时间，最多等待约 6 分钟）
            for _ in range(180):
                time.sleep(2)
                if self.is_available():
                    self.logger("mineru-api 已就绪")
                    return True
                if self._proc and self._proc.poll() is not None:
                    self._close_log_fp()
                    self.logger(f"mineru-api 进程已退出，详见日志: {self._log_path}")
                    return False
            self._close_log_fp()
            self.logger(f"mineru-api 启动超时，详见日志: {self._log_path}")
            return False

    def _close_log_fp(self):
        """关闭子进程日志文件句柄"""
        try:
            if getattr(self, "_log_fp", None) and not self._log_fp.closed:
                self._log_fp.flush()
                self._log_fp.close()
        except Exception:
            pass

    def parse_to_markdown(self, file_path: str) -> str:
        """调用 /file_parse 解析单文件，返回 Markdown 文本；失败抛 RuntimeError"""
        if not self.ensure_started():
            raise RuntimeError("MinerU 服务不可用（mineru-api 未启动）")
        try:
            with open(file_path, "rb") as f:
                files = {"files": (os.path.basename(file_path), f)}
                data = {
                    "return_md": "true",
                    "response_format_zip": "false",
                    "parse_method": "auto",
                }
                # backend=auto 时不传该参数，由 mineru-api 使用默认后端
                if self.backend and self.backend != "auto":
                    data["backend"] = self.backend
                r = requests.post(
                    f"{self.api_url}/file_parse", files=files, data=data, timeout=1800
                )
        except Exception as e:
            raise RuntimeError(f"调用 /file_parse 失败: {e}")
        if r.status_code != 200:
            raise RuntimeError(f"/file_parse 返回 {r.status_code}: {r.text[:300]}")
        md = self._extract_markdown(r)
        if not md:
            raise RuntimeError("未能从 /file_parse 响应中提取到 Markdown 内容")
        return md

    @staticmethod
    def _extract_markdown(r) -> str:
        """从 /file_parse 响应中尽量稳健地提取 Markdown 文本"""
        # 优先按 JSON 解析
        try:
            data = r.json()
        except Exception:
            t = r.text or ""
            return t.strip()

        candidates = []

        def collect(obj):
            if isinstance(obj, str):
                if obj.strip():
                    candidates.append(obj)
            elif isinstance(obj, dict):
                # 先收集已知的 markdown 内容字段
                for k in ("md", "md_content", "markdown", "markdown_content", "text", "content"):
                    v = obj.get(k)
                    if isinstance(v, str) and v.strip():
                        candidates.append(v)
                # 再递归遍历所有 dict 值（文件名等动态键名也能到达 md_content）
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        collect(v)
            elif isinstance(obj, list):
                for it in obj:
                    collect(it)

        collect(data)
        if candidates:
            # 取最长候选作为正文
            return max(candidates, key=len)
        return ""
