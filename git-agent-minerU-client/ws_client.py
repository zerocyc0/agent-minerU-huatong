# encoding: utf-8
# @file: ws_client.py
# @desc: agent-minerU WebSocket 客户端（Web 后端专用）。
#        Web 端只有「文件上传分析」一种入口（单文件 / 多文件统一处理，浏览器文件
#        只能上传，不存在服务端本地路径 / 纯文本提问场景）。
#        发送给 agent-minerU 服务端的 JSON 与 client_socket/ws_client.py 的
#        WebSocketTestClient.upload_files 协议一致，并额外携带 staff_id
#        （服务端 websocket_handler 会读取 staff_id 并写入 material_analysis 表）：
#          {
#            "files": [{"name": "a.pdf", "data": "<base64>"}, ...],
#            "summary": true,                 # 始终携带（bool）
#            "staff_id": "admin",             # 工号，服务端入库到 material_analysis.staff_id
#            "question": "...",               # 可空，空则不携带
#            "summary_instruction": "..."     # 可空，空则不携带
#          }
#        注意：不携带 mode / items 等多余字段。
#        文件分析为耗时操作（MinerU+LLM），采用后台线程任务 + 前端轮询。
import base64
import json
import os
import threading
import time
import uuid
import configparser
from typing import Any, Dict, List, Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(_BASE_DIR, "config.ini"), encoding="utf-8")

WS_URL = _cfg.get("agent", "ws_url", fallback="ws://127.0.0.1:8765")
WS_TIMEOUT = _cfg.getint("agent", "timeout", fallback=3600)

_tasks: dict = {}
_lock = threading.Lock()


def get_task(task_id: str) -> Optional[dict]:
    with _lock:
        task = _tasks.get(task_id)
        return dict(task) if task else None


def _make_task(payload: Any, file_names: List[str], staff_id: str,
               question: str = "") -> dict:
    task_id = uuid.uuid4().hex
    task = {
        "task_id": task_id,
        "status": "running",                # running / done / error
        "mode": "files",                    # 与服务端返回的 data.mode 词汇一致
        "file_names": file_names,
        "file_count": len(file_names),
        "question": question or "",
        "staff_id": staff_id,               # 仅本地审计/权限用，不发给服务端
        "created": time.time(),
        "elapsed": None,
        "result": None,                     # agent_response 完整 JSON
        "error": None,
    }
    with _lock:
        _tasks[task_id] = task
    threading.Thread(target=_run, args=(task, payload), daemon=True).start()
    return task


# ---------------- 唯一业务入口：文件上传分析（1 个或多个文件） ----------------

def create_upload_task(files, question: str, staff_id: str, *,
                       summary: bool = True,
                       summary_instruction: str = "") -> dict:
    """文件上传分析（对应 client_socket.WebSocketTestClient.upload_files）。
    files: werkzeug FileStorage 列表（1..N 个，单文件/多文件统一走此入口）。
    返回本地任务 dict；后台线程负责连接 WS 并发送与参考客户端完全一致的 JSON。
    """
    items: List[Dict[str, str]] = []
    names: List[str] = []
    total_bytes = 0
    for fs in files:
        raw = fs.read()
        name = os.path.basename(fs.filename or "unnamed") or "unnamed"
        names.append(name)
        total_bytes += len(raw)
        items.append({"name": name,
                      "data": base64.b64encode(raw).decode("ascii")})

    q = (question or "").strip()
    si = (summary_instruction or "").strip()
    sid = (staff_id or "").strip()
    # 对齐参考客户端 upload_files 的字段：files + summary 必带；
    # staff_id 必带（服务端入库 material_analysis.staff_id）；
    # question / summary_instruction 非空才带；不带 mode/items 等多余字段。
    payload: Dict[str, Any] = {
        "files": items,
        "summary": bool(summary),
        "staff_id": sid,
    }
    if q:
        payload["question"] = q
    if si:
        payload["summary_instruction"] = si

    task = _make_task(payload, names, staff_id, question=q)
    print(f"[WS] 任务 {task['task_id'][:8]}… 待发送: files={len(items)} "
          f"({total_bytes} 字节, base64 后约 {int(total_bytes * 4 / 3 / 1024)} KB) "
          f"summary={bool(summary)} question={q[:40]!r}", flush=True)
    return task


# ---------------- 发送执行 ----------------

def _build_message(payload: Any) -> str:
    """dict/list -> JSON 字符串；str 原样发送（保留裸文本能力）。"""
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


def _run(task: dict, payload: Any) -> None:
    import websocket  # websocket-client
    start = time.time()
    try:
        msg = _build_message(payload)
        if isinstance(payload, dict):
            files = payload.get("files") or []
            print(f"[WS] -> {WS_URL}  keys={sorted(payload.keys())} "
                  f"files={len(files)} summary={payload.get('summary')} "
                  f"question={str(payload.get('question', ''))[:40]!r}", flush=True)
        # 连接超时 10 秒；连接成功后读超时放大到分析超时
        ws = websocket.create_connection(WS_URL, timeout=10)
        ws.settimeout(WS_TIMEOUT)
        try:
            ws.send(msg)
            while True:
                raw = ws.recv()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                resp = json.loads(raw)
                resp_type = resp.get("type")
                if resp_type == "agent_response":
                    task["result"] = resp
                    # 服务端业务失败（status=500）也算任务失败，直接提示错误原因
                    if resp.get("status") == 500:
                        task["error"] = (resp.get("data") or {}).get("error") \
                            or "agent-minerU 服务端分析失败"
                    break
                if resp_type == "binary_ack":
                    continue
                # 其它类型（回显/中间消息）：忽略并继续等待 agent_response
        finally:
            try:
                ws.close()
            except Exception:
                pass
        task["status"] = "error" if task.get("error") else "done"
        if task["status"] == "done":
            data = (task.get("result") or {}).get("data") or {}
            print(f"[WS] <- 任务 {task['task_id'][:8]}… 分析完成: "
                  f"total={data.get('total')} success={data.get('success_count')} "
                  f"fail={data.get('fail_count')}", flush=True)
        else:
            print(f"[WS] <- 任务 {task['task_id'][:8]}… 服务端返回失败: "
                  f"{task.get('error')}", flush=True)
    except Exception as e:
        task["status"] = "error"
        task["error"] = f"{e}（请确认 agent-minerU 服务 {WS_URL} 已启动）"
        print(f"[WS] !! 任务 {task['task_id'][:8]}… 连接/发送失败: {e}", flush=True)
    finally:
        task["elapsed"] = round(time.time() - start, 1)
