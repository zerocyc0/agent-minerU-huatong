# encoding: utf-8
# @file: app.py
# @desc: 华通物料智能分析平台 Flask 服务。
#        1. 用户管理: 注册/登录、管理员菜单授权与收回（staff_id 员工工号为主键）
#        2. 文件分析: 多文件上传 -> agent-minerU WebSocket 分析 -> 结果可编辑
#                     保存到 material_analysis_last（修改行 edit_date 写保存时间）
#        3. 数据查询: 按时间段查询本人解析数据，默认当日，柱状图展示条数
import configparser
import re
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session

import db
import ws_client

app = Flask(__name__)

_c = configparser.ConfigParser()
_c.read("config.ini", encoding="utf-8")
app.secret_key = _c.get("app", "secret_key", fallback="huatong-secret")
app.config["MAX_CONTENT_LENGTH"] = 90 * 1024 * 1024   # 总上传 ≤90MB（base64 后 <128MB 服务限制）
app.json.ensure_ascii = False

STAFF_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,50}$")


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


@app.errorhandler(Exception)
def _global_exception_handler(ex: Exception):
    """捕获 ALL 未处理异常（包括 multipart 解析失败、装饰器、视图内未捕获等），统一返回 JSON + 栈，
    这样前端 app.js 就不会把默认 Flask 500 HTML 当成「响应异常」糊成文字，而能看到真正错误原因。
    同时日志落 stdout 以便后台排查。"""
    import traceback as _tb
    tb = _tb.format_exc()
    log(f"[GLOBAL-500] {type(ex).__name__}: {ex}")
    for line in tb.splitlines(): log("  > " + line)
    status = getattr(ex, "code", None)
    if not isinstance(status, int): status = 500
    if status < 400: status = 500
    return jsonify({
        "code": status,
        "message": f"{type(ex).__name__}: {ex}",
        "traceback": tb,
    }), status


# ---------------------------------------------------------------- 认证装饰器

def _fresh_user():
    """从数据库读取最新用户状态（权限/禁用立即生效），无效则清除会话"""
    u = session.get("user")
    if not u:
        return None
    fresh = db.get_user_by_staff_id(u.get("staff_id", ""))
    if not fresh or not fresh["status"]:
        session.clear()
        return None
    session["user"] = fresh
    return fresh


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not _fresh_user():
            return jsonify({"code": 401, "message": "未登录或会话已过期"}), 401
        return fn(*a, **kw)
    return wrapper


def perm_required(perm_key: str):
    """菜单权限校验；admin 角色默认拥有全部权限"""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = _fresh_user()
            if not u:
                return jsonify({"code": 401, "message": "未登录或会话已过期"}), 401
            if u["role"] != "admin" and not u[perm_key]:
                return jsonify({"code": 403, "message": "没有该功能权限，请联系管理员授权"}), 403
            return fn(*a, **kw)
        return wrapper
    return deco


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        u = _fresh_user()
        if not u:
            return jsonify({"code": 401, "message": "未登录或会话已过期"}), 401
        if u["role"] != "admin":
            return jsonify({"code": 403, "message": "仅管理员可执行此操作"}), 403
        return fn(*a, **kw)
    return wrapper


# ---------------------------------------------------------------- 页面路由

@app.route("/")
def index():
    return redirect("/app" if session.get("user") else "/login")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/app")
def app_page():
    if not session.get("user"):
        return redirect("/login")
    return render_template("app.html")


# ---------------------------------------------------------------- 认证 API

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    d = request.get_json(silent=True) or {}
    staff_id = str(d.get("staff_id") or "").strip()
    username = str(d.get("username") or "").strip()
    password = str(d.get("password") or "")
    real_name = str(d.get("real_name") or "").strip()
    if not STAFF_ID_RE.match(staff_id):
        return jsonify({"code": 400, "message": "员工工号须为 2-50 位字母/数字/下划线/中划线"})
    if len(username) < 2:
        return jsonify({"code": 400, "message": "用户名至少 2 个字符"})
    if len(password) < 6:
        return jsonify({"code": 400, "message": "密码至少 6 位"})
    if db.get_user_by_staff_id(staff_id):
        return jsonify({"code": 400, "message": f"工号 {staff_id} 已注册"})
    if db.get_user_by_username(username):
        return jsonify({"code": 400, "message": "用户名已存在"})
    # 新注册为普通员工，菜单功能需管理员授权
    user = db.create_user(staff_id, username, password, real_name, role="employee")
    session["user"] = user
    log(f"用户注册: {username}({staff_id})")
    return jsonify({"code": 200, "message": "注册成功", "data": {"user": user}})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    d = request.get_json(silent=True) or {}
    username = str(d.get("username") or "").strip()
    password = str(d.get("password") or "")
    try:
        user = db.verify_login(username, password)
    except PermissionError as e:
        return jsonify({"code": 403, "message": str(e)})
    if not user:
        return jsonify({"code": 400, "message": "用户名或密码错误"})
    session["user"] = user
    log(f"用户登录: {username}({user['staff_id']})")
    return jsonify({"code": 200, "message": "登录成功", "data": {"user": user}})


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def api_logout():
    session.clear()
    return jsonify({"code": 200, "message": "已退出登录"})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def api_me():
    return jsonify({"code": 200, "data": {"user": _fresh_user()}})


@app.route("/api/config", methods=["GET"])
@login_required
def api_config():
    """向前端暴露 WebSocket 直连配置（浏览器直接连 agent-minerU，不经过 Flask 代理）。
       同时返回当前登录员工的 staff_id，前端会把 staff_id 附加到 WS 消息中，
       以便服务端解析后在回包中带上身份标识。"""
    import ws_client as _wc
    ws_url = _wc.WS_URL
    # 若浏览器从非本机访问，尝试把 127.0.0.1 替换成当前访问主机(方便跨机调试)，但端口保留
    host = request.host.split(":", 1)[0] if request.host else None
    ws_url_public = ws_url
    if host and host not in ("127.0.0.1", "localhost", ""):
        import re as _re
        ws_url_public = _re.sub(
            r"ws://(127\.0\.0\.1|localhost|0\.0\.0\.0)(:\d+)",
            f"ws://{host}\\2", ws_url)
    return jsonify({"code": 200, "data": {
        "ws_url": ws_url,
        "ws_url_public": ws_url_public,
        "ws_timeout": int(getattr(_wc, "WS_TIMEOUT", 3600)),
        "staff_id": _fresh_user()["staff_id"],
        "max_content_mb": int(app.config.get("MAX_CONTENT_LENGTH", 90 * 1024 * 1024) // (1024 * 1024)),
    }})


# ---------------------------------------------------------------- 用户管理 API（管理员）

@app.route("/api/users", methods=["GET"])
@admin_required
def api_users():
    return jsonify({"code": 200, "data": {"users": db.list_users()}})


@app.route("/api/users", methods=["POST"])
@admin_required
def api_users_create():
    d = request.get_json(silent=True) or {}
    staff_id = str(d.get("staff_id") or "").strip()
    username = str(d.get("username") or "").strip()
    password = str(d.get("password") or "")
    if not STAFF_ID_RE.match(staff_id):
        return jsonify({"code": 400, "message": "员工工号须为 2-50 位字母/数字/下划线/中划线"})
    if len(username) < 2:
        return jsonify({"code": 400, "message": "用户名至少 2 个字符"})
    if len(password) < 6:
        return jsonify({"code": 400, "message": "密码至少 6 位"})
    if db.get_user_by_staff_id(staff_id):
        return jsonify({"code": 400, "message": f"工号 {staff_id} 已存在"})
    if db.get_user_by_username(username):
        return jsonify({"code": 400, "message": "用户名已存在"})
    role = "admin" if d.get("role") == "admin" else "employee"
    user = db.create_user(
        staff_id, username, password, str(d.get("real_name") or "").strip(),
        role=role,
        perm_analysis=bool(d.get("perm_analysis")),
        perm_query=bool(d.get("perm_query")))
    log(f"管理员新增用户: {username}({staff_id})")
    return jsonify({"code": 200, "message": "新增成功", "data": {"user": user}})


@app.route("/api/users/<staff_id>", methods=["PUT"])
@admin_required
def api_users_update(staff_id: str):
    me = _fresh_user()
    target = db.get_user_by_staff_id(staff_id)
    if not target:
        return jsonify({"code": 404, "message": "用户不存在"}), 404
    d = request.get_json(silent=True) or {}
    # 防止管理员把自己锁死
    if staff_id == me["staff_id"] and ("role" in d or "status" in d):
        return jsonify({"code": 400, "message": "不能修改自己的角色或状态"})
    # 内置管理员保护
    if staff_id == "admin" and ("role" in d or "status" in d):
        return jsonify({"code": 400, "message": "内置管理员账号不允许修改角色或禁用"})
    if d.get("password") and len(str(d["password"])) < 6:
        return jsonify({"code": 400, "message": "密码至少 6 位"})
    data = {}
    for k in ("real_name", "role"):
        if k in d:
            data[k] = d[k]
    for k in ("perm_analysis", "perm_query", "status"):
        if k in d:
            data[k] = bool(d[k])
    if d.get("password"):
        data["password"] = str(d["password"])
    user = db.update_user(staff_id, data)
    log(f"管理员更新用户 {staff_id}: {', '.join(data.keys())}")
    return jsonify({"code": 200, "message": "保存成功", "data": {"user": user}})


@app.route("/api/users/<staff_id>", methods=["DELETE"])
@admin_required
def api_users_delete(staff_id: str):
    me = _fresh_user()
    if staff_id == me["staff_id"]:
        return jsonify({"code": 400, "message": "不能删除当前登录账号"})
    if staff_id == "admin":
        return jsonify({"code": 400, "message": "内置管理员账号不允许删除"})
    if not db.get_user_by_staff_id(staff_id):
        return jsonify({"code": 404, "message": "用户不存在"}), 404
    db.delete_user(staff_id)
    log(f"管理员删除用户: {staff_id}")
    return jsonify({"code": 200, "message": "删除成功"})


# ---------------------------------------------------------------- 文件分析 API
# Web 端只有「文件上传分析」一种入口（单文件 / 多文件统一处理；浏览器文件只能上传，
# 不存在纯文本提问 / 服务端本地路径分析场景）。
# 发送给 agent-minerU 的 JSON 与 client_socket/ws_client.py 的
# WebSocketTestClient.upload_files 完全一致：
#   {"files":[{"name":"a.pdf","data":"<base64>"}, ...],
#    "summary": true|false, "question"?: "...", "summary_instruction"?: "..."}


@app.route("/api/analysis/upload", methods=["POST"])
@perm_required("perm_analysis")
def api_analysis_upload():
    """文件上传分析入口 (multipart)。单文件/多文件统一走此入口，
       后台经 ws_client 发送与 client_socket.upload_files 完全一致的 JSON。
    """
    import traceback as _tb
    try:
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            return jsonify({"code": 400, "message": "请选择要分析的文件"})
        question = str(request.form.get("question") or "").strip()
        summary = request.form.get("summary", "1") not in ("0", "false", "False", "no")
        summary_instruction = str(request.form.get("summary_instruction") or "").strip()
        staff_id = _fresh_user()["staff_id"]
        task = ws_client.create_upload_task(files, question, staff_id,
                                            summary=summary,
                                            summary_instruction=summary_instruction)
        log(f"[文件分析/上传] 创建任务 {task['task_id'][:8]}… 文件数={task['file_count']} "
            f"工号={staff_id} summary={summary}")
        return jsonify({"code": 200, "message": "任务已提交", "data": {"task": task}})
    except Exception as e:
        log(f"[文件分析/上传] 异常: {type(e).__name__}: {e}")
        log(_tb.format_exc())
        return jsonify({"code": 500, "message": f"{type(e).__name__}: {e}",
                        "traceback": _tb.format_exc(limit=12)}), 500


@app.route("/api/analysis/task/<task_id>", methods=["GET"])
@perm_required("perm_analysis")
def api_analysis_task(task_id: str):
    task = ws_client.get_task(task_id)
    if not task:
        return jsonify({"code": 404, "message": "任务不存在或已过期"}), 404
    u = _fresh_user()
    if task["staff_id"] != u["staff_id"] and u["role"] != "admin":
        return jsonify({"code": 403, "message": "无权查看该任务"}), 403
    return jsonify({"code": 200, "data": {"task": task}})


@app.route("/api/analysis/save", methods=["POST"])
@perm_required("perm_analysis")
def api_analysis_save():
    d = request.get_json(silent=True) or {}
    rows = d.get("rows") or []
    if not rows:
        return jsonify({"code": 400, "message": "没有可保存的数据"})
    res = db.save_analysis_rows(rows, _fresh_user()["staff_id"], logger=log)
    total = len(rows)
    ins = int(res.get("inserted") or 0)
    upd = int(res.get("updated") or 0)
    skp = int(res.get("skipped") or 0)
    err = res.get("errors") or []
    parts = []
    if ins: parts.append("新增 %d 条" % ins)
    if upd: parts.append("更新 %d 条" % upd)
    if skp and skp == total:
        # 全部已保存过且用户没改：按用户习惯提示一句，不要显示“保存 0 条”
        msg = "数据已经保存过了，无需重复保存"
    else:
        if skp: parts.append("已保存跳过 %d 条" % skp)
        if err: parts.append("%d 条失败: %s" % (len(err), str(err[0])[:80]))
        if not parts: parts.append("没有数据变更")
        msg = "保存确认结果：" + "，".join(parts) + "（共 %d 条）" % total
    code = 200
    if not ins and not upd and err:
        code = 500 if not skp else 409
    return jsonify({"code": code, "message": msg, "data": res})


# ---------------------------------------------------------------- 数据查询 API

@app.route("/api/query", methods=["GET"])
@perm_required("perm_query")
def api_query():
    def _valid_date(s):
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return s
        except (ValueError, TypeError):
            return None

    start = _valid_date(request.args.get("start"))
    end = _valid_date(request.args.get("end"))
    if not start or not end:
        today = datetime.now().strftime("%Y-%m-%d")
        start = end = today          # 默认查询当日
    if end < start:
        start, end = end, start
    table = request.args.get("table", "material_analysis")
    if table not in db.QUERY_TABLES:
        return jsonify({"code": 400, "message": "不支持的数据表"})

    u = _fresh_user()
    staff_filter = u["staff_id"]     # 普通员工只能查本人数据
    if u["role"] == "admin":
        staff_filter = request.args.get("staff_id", "").strip() or None
    rows = db.query_materials(start, end, table, staff_filter)
    chart = db.build_chart(rows, start, end)

    file_sns = {r["file_sn"] for r in rows}
    summary = {
        "total": len(rows),
        "files": len(file_sns),
        "first": min((r["create_date"] for r in rows), default=""),
        "last": max((r["create_date"] for r in rows), default=""),
    }
    return jsonify({"code": 200, "data": {
        "rows": rows, "chart": chart, "summary": summary,
        "start": start, "end": end, "table": table}})


# ---------------------------------------------------------------- 启动

if __name__ == "__main__":
    if not db.init_db(logger=log):
        log("警告: 数据库初始化失败，请检查 config.ini 中的 MySQL 配置")
    host = _c.get("app", "host", fallback="0.0.0.0")
    port = _c.getint("app", "port", fallback=5000)
    log(f"Flask 服务启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
