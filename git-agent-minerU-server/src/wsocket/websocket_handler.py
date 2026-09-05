# encoding: utf-8
# @file: websocket_handler.py
# @desc: WebSocket 服务端处理。接收客户端文件/文本，统一保存到 config.ini 配置目录，
#        调用 MinerU+LLM 两阶段管线分析，返回含返回码与文件标识的 JSON。
import asyncio
import websockets
import threading
import time
import json
import os
import base64
import shutil
from PyQt5.QtCore import QObject, pyqtSignal

from analyzer.document_analyzer import DocumentAnalyzer
from config_manager import (
    get_save_dir, get_max_file_size, build_save_path,
    get_server_config,
)


# 全局消息常量
MSG = {
    200: "解析成功",
    400: "请求参数错误",
    404: "文件不存在",
    413: "文件超过大小限制",
    415: "不支持的文件类型",
    422: "文件解析失败或内容为空",
    503: "解析服务不可用（MinerU/LLM）",
    500: "服务器内部错误",
}


class WebSocketHandler(QObject):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    client_count_signal = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.clients = set()
        self.server = None
        self.loop = None
        self.thread = None

    @staticmethod
    def _parse_request(message: str) -> dict:
        """
        解析客户端消息：
        - {"mode":"files","items":[{"name":str,"data":str|None}],"question":str}
        - 单文件 {"file_path": ...} 或 {"files": [...]} / {"file_paths":[...]} 自动归一为 files 模式
        - 纯文本 {"question": str} 或裸字符串 -> text 模式
        """
        try:
            req = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return {"mode": "text", "query": message}
        if not isinstance(req, dict):
            return {"mode": "text", "query": message}

        question = str(req.get("question") or "").strip()
        staff_id = str(req.get("staff_id") or "").strip()

        files = req.get("files") or req.get("file_paths")
        single_path = str(req.get("file_path") or "").strip()
        if single_path and not files:
            files = [single_path]

        if isinstance(files, list) and files:
            items = []
            for f in files:
                if isinstance(f, dict):
                    name = str(f.get("name") or f.get("file_path") or "").strip()
                    items.append({"name": name, "data": f.get("data")})
                else:
                    items.append({"name": str(f).strip(), "data": None})
            if items:
                return {"mode": "files", "items": items,
                        "question": question, "staff_id": staff_id}

        if question:
            return {"mode": "text", "query": question, "staff_id": staff_id}
        return {"mode": "text", "query": message, "staff_id": staff_id}

    def _log(self, msg: str):
        self.log_signal.emit(f"[{time.strftime('%H:%M:%S')}] {msg}")

    async def _handle_files(self, items: list, question: str, loop,
                           staff_id: str = "") -> dict:
        """
        统一文件处理：
        阶段1: 所有文件统一保存到 config.ini 配置目录
              - 含 base64 数据: 解码保存
              - 纯路径项: 复制到配置目录（已在目录内的直接使用）
              - 路径不存在: 404 错误条目
        阶段2: 并发两阶段分析（每文件独立会话）
        阶段3: 一个文件生成一个 file_sn(文件编号)，每条数据按 data_sn(顺序号1,2,3...)
               区分，随响应返回客户端。物料条目复用同一 file_sn + data_sn 写入
               MySQL material_analysis 表（file_name 保存文件名，staff_id 由客户端传入）
        """
        save_dir = os.path.abspath(get_save_dir())
        max_size = get_max_file_size()
        results = []
        success_count = 0
        fail_count = 0
        analysis_paths = []  # [{"file_name", "file_path"}]
        uploaded = False

        # 1. 统一保存所有文件到配置目录
        for item in items:
            name = item.get("name") or ""
            data = item.get("data")
            file_name = os.path.basename(name) or "unnamed"
            entry = {"file_name": file_name}

            if not name:
                entry["file_path"] = None
                entry["code"] = 400
                entry["message"] = MSG[400] + "：缺少文件名"
                fail_count += 1
                results.append(entry)
                continue

            if data:
                # base64 上传文件
                uploaded = True
                try:
                    file_bytes = base64.b64decode(data)
                except Exception as e:
                    entry["file_path"] = None
                    entry["code"] = 400
                    entry["message"] = MSG[400] + f"：base64 解码失败: {e}"
                    fail_count += 1
                    results.append(entry)
                    continue
                if len(file_bytes) > max_size:
                    entry["file_path"] = None
                    entry["code"] = 413
                    entry["message"] = MSG[413] + f"（限制 {max_size} 字节）"
                    fail_count += 1
                    results.append(entry)
                    continue
                try:
                    save_path = build_save_path(name)
                    with open(save_path, "wb") as f:
                        f.write(file_bytes)
                    self._log(f"上传文件已保存: {save_path} ({len(file_bytes)}字节)")
                    entry["file_path"] = save_path
                    analysis_paths.append({"file_name": file_name, "file_path": save_path})
                    entry["_pending"] = True
                except Exception as e:
                    entry["file_path"] = None
                    entry["code"] = 500
                    entry["message"] = MSG[500] + f"：保存失败: {e}"
                    fail_count += 1
                    results.append(entry)
                    continue
            else:
                # 纯路径文件: 统一复制到配置目录
                src_path = os.path.abspath(name)
                if not os.path.isfile(src_path):
                    entry["file_path"] = None
                    entry["code"] = 404
                    entry["message"] = MSG[404] + f"：文件不存在: {name}"
                    fail_count += 1
                    results.append(entry)
                    continue
                try:
                    if os.path.dirname(src_path) == save_dir:
                        save_path = src_path
                        self._log(f"使用已保存文件: {save_path}")
                    else:
                        save_path = build_save_path(name)
                        shutil.copy2(src_path, save_path)
                        self._log(f"文件已保存: {src_path} -> {save_path}")
                    entry["file_path"] = save_path
                    analysis_paths.append({"file_name": file_name, "file_path": save_path})
                    entry["_pending"] = True
                except Exception as e:
                    entry["file_path"] = None
                    entry["code"] = 500
                    entry["message"] = MSG[500] + f"：保存失败: {e}"
                    fail_count += 1
                    results.append(entry)
                    continue

            results.append(entry)

        # 2. 并发两阶段分析
        if analysis_paths:
            tasks = []
            for af in analysis_paths:
                tasks.append(loop.run_in_executor(
                    None, DocumentAnalyzer.analyze_file_pipeline,
                    af["file_path"], question, self._log
                ))
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            pending = [e for e in results if e.get("_pending")]
            for entry, af, r in zip(pending, analysis_paths, raw_results):
                entry.pop("_pending", None)
                entry["file_name"] = af["file_name"]
                entry["file_path"] = af["file_path"]
                if isinstance(r, Exception):
                    entry["code"] = 500
                    entry["message"] = MSG[500] + f"：{r}"
                    fail_count += 1
                elif not isinstance(r, dict):
                    entry["code"] = 500
                    entry["message"] = MSG[500] + "：分析返回异常"
                    fail_count += 1
                else:
                    code = r.get("code", 200)
                    entry["code"] = code
                    entry["message"] = MSG.get(code, "未知状态")
                    if "error" in r:
                        entry["message"] = entry["message"] + f"：{r['error']}"
                    if code == 200:
                        entry["parser"] = (r.get("metadata") or {}).get("parser")
                        entry["analysis"] = r.get("analysis")
                        entry["answer"] = r.get("answer")
                        entry["first_analysis"] = r.get("first_analysis")
                        success_count += 1
                        # 阶段3: 一个文件生成一个 file_sn，每条数据按 data_sn(1,2,3...)
                        # 区分，随响应返回客户端。MySQL 写库复用同一 file_sn + data_sn。
                        # 即使写库被禁用或失败，编号也已生成并返回。
                        items_data = (r.get("analysis") or {}).get("items") or []
                        if items_data:
                            from db.mysql_manager import generate_file_sn
                            file_sn = generate_file_sn()
                            data_sns = list(range(1, len(items_data) + 1))
                            entry["file_sn"] = file_sn
                            entry["data_sns"] = data_sns
                            db_res = await loop.run_in_executor(
                                None, self._save_to_mysql, items_data, staff_id,
                                file_sn, data_sns, af["file_name"]
                            )
                            entry["db_saved"] = db_res.get("saved", 0)
                            if db_res.get("error"):
                                entry["db_error"] = db_res["error"]
                                self._log(f"MySQL 保存失败({af['file_name']}): {db_res['error']}")
                            elif db_res.get("skipped"):
                                self._log("MySQL 已在配置中禁用，跳过写库")
                            else:
                                self._log(
                                    f"MySQL 已保存 {db_res.get('saved', 0)} 条记录: {af['file_name']}"
                                )
                    else:
                        fail_count += 1

        # 兜底清理 pending 标记
        for e in results:
            e.pop("_pending", None)

        # 整体返回码：全部成功 200，部分成功 207，全部失败取最严重错误码
        total = len(results)
        if fail_count == 0:
            overall_code = 200
        elif success_count > 0:
            overall_code = 207
        else:
            # 全部失败：取首个失败条目码作为整体码
            overall_code = next(
                (e["code"] for e in results if e.get("code") and e["code"] != 200), 422
            )

        data = {
            "mode": "files",
            "total": total,
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results,
        }
        if uploaded:
            data["save_dir"] = save_dir
        return {"code": overall_code, "message": MSG.get(overall_code, ""), "data": data}

    async def handler(self, websocket):
        client_ip = websocket.remote_address if websocket.remote_address else "Unknown"
        self.clients.add(websocket)
        self._log(f"新客户端连接: {client_ip}")
        self.update_client_count()
        try:
            async for message in websocket:
                if isinstance(message, str):
                    self._log(f"收到消息: {message[:200]}{'...' if len(message) > 200 else ''}")
                    try:
                        req = self._parse_request(message)
                        loop = asyncio.get_running_loop()
                        if req["mode"] == "files":
                            data = await self._handle_files(
                                req["items"], req.get("question", ""), loop,
                                staff_id=req.get("staff_id", "")
                            )
                            response = {"type": "agent_response", "code": data["code"],
                                        "message": data["message"], "data": data["data"]}
                        else:
                            # 纯文本提问：直接由 LLM 回答
                            answer = await loop.run_in_executor(
                                None, self._answer_text, req["query"]
                            )
                            response = {"type": "agent_response", "code": answer["code"],
                                        "message": answer["message"], "data": answer["data"]}
                    except Exception as e:
                        response = {"type": "agent_response", "code": 500,
                                    "message": MSG[500], "data": {"error": str(e)}}

                    self._log(f"返回结果: {json.dumps(response, ensure_ascii=False)[:200]}")
                    await websocket.send(json.dumps(response, ensure_ascii=False))
                elif isinstance(message, bytes):
                    response = {"type": "binary_ack", "code": 200,
                                "message": "二进制数据已接收（请使用 files 协议上传文件）", "data": None}
                    await websocket.send(json.dumps(response, ensure_ascii=False))
        except websockets.exceptions.ConnectionClosed:
            self._log(f"客户端断开连接: {client_ip}")
        finally:
            self.clients.discard(websocket)
            self.update_client_count()

    def _save_to_mysql(self, items: list, staff_id: str,
                       file_sn: str = None, data_sns: list = None,
                       file_name: str = None) -> dict:
        """将物料条目保存到 MySQL（在线程池中执行），复用分析结果阶段生成的 file_sn + data_sns"""
        try:
            from db.mysql_manager import save_material_items
            return save_material_items(items, staff_id=staff_id, logger=self._log,
                                       file_sn=file_sn, data_sns=data_sns,
                                       file_name=file_name)
        except Exception as e:
            return {"saved": 0, "file_sn": file_sn or "", "data_sns": data_sns or [],
                    "error": str(e)}

    @staticmethod
    def _answer_text(query: str) -> dict:
        """纯文本提问直接由 DeepSeek（langchain ChatOpenAI）回答"""
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import SystemMessage, HumanMessage
            from agent.load_env import load_env
            env = load_env()
            llm = ChatOpenAI(
                model=env["llm_model"],
                api_key=env["API_KEY"],
                base_url=env["base_url"],
                temperature=0,
            )
            resp = llm.invoke([
                SystemMessage(content="你是电线电缆行业助理，请用中文简洁回答用户问题。"),
                HumanMessage(content=query)
            ])
            return {"code": 200, "message": MSG[200],
                    "data": {"mode": "text", "answer": resp.content}}
        except Exception as e:
            return {"code": 503, "message": MSG[503], "data": {"error": str(e)}}

    def update_client_count(self):
        count = len(self.clients)
        self.client_count_signal.emit(count)
        self.status_signal.emit(f"当前在线: {count}")

    def start_server(self, host=None, port=None):
        if self.thread and self.thread.is_alive():
            self._log("警告: 服务已在运行中")
            return

        if not host or not port:
            cfg = get_server_config()
            host = host or cfg["host"]
            port = port or cfg["port"]

        self.loop = asyncio.new_event_loop()

        async def main():
            self.server = await websockets.serve(
                self.handler, host, port,
                ping_interval=20, ping_timeout=60,
                reuse_address=True,
                max_size=128 * 1024 * 1024,  # 128MB，支持多文件 base64 上传
            )
            self.status_signal.emit(f"服务运行中 ws://{host}:{port}")
            self._log(f"服务已启动 ws://{host}:{port}")
            await asyncio.Future()

        def run_loop():
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(main())
            except Exception as e:
                if "Event loop stopped" not in str(e):
                    self._log(f"服务异常: {e}")
            finally:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                if not self.loop.is_closed():
                    self.loop.close()

        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()

    def stop_server(self):
        self._log("正在停止服务...")

        if not self.loop or self.loop.is_closed():
            self.status_signal.emit("服务未运行")
            return

        async def shutdown():
            if self.server:
                self.server.close()
                await self.server.wait_closed()
                self._log("监听已关闭")
            if self.clients:
                close_tasks = [c.close() for c in self.clients]
                await asyncio.gather(*close_tasks, return_exceptions=True)
                self.clients.clear()
                self._log("所有客户端连接已断开")

        try:
            future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
            future.result(timeout=10)
        except Exception as e:
            self._log(f"关闭过程中出错: {e}")

        self.loop.call_soon_threadsafe(self.loop.stop)

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

        self.status_signal.emit("服务已停止")
        self._log("服务完全停止，资源已释放")
