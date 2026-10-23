"""
finals/app.py
-------------
Flask backend độc lập cho vòng chung kết.

Chạy:
  # SQLite được tạo tự động tại finals/finals.db
  set FINALS_ADMIN_SECRET=adminpass
  python -m finals.app

Endpoints:
  POST /finals/auth/login          { username, password } → { token }
  POST /finals/auth/logout         Header: X-Finals-Token
  GET  /finals/me                  Header: X-Finals-Token → thông tin sinh viên

  POST /finals/matches             Header: X-Finals-Token (admin only)
                                   Body: { player_a, player_b, request_id? }
                                   → { request_id, match_id, queued }
  GET  /finals/matches/<request_id>  → trạng thái + kết quả
  GET  /finals/matches             → danh sách trận (có phân trang)
  GET  /finals/standings           → bảng xếp hạng tổng

  -- Admin --
  POST /finals/admin/contestants   { username, password, display_name, student_id? }
  POST /finals/admin/import-finalists  multipart CSV → offline usernames/passwords
  GET  /finals/admin/contestants   → danh sách sinh viên
  DELETE /finals/admin/contestants/<username>
  GET  /finals/admin/queue         → trạng thái hàng đợi
  POST /finals/admin/bots/snapshot { username }  → chốt bot (copy latest.py → snaps/finals/)
"""
import logging
import os
import sys
import secrets
import csv
import io

from flask import Flask, request, jsonify, g, Response, send_from_directory
import json
import queue

from .logger_setup import setup as setup_logging

# Khởi tạo logging sớm nhất
_log_level = os.environ.get("FINALS_LOG_LEVEL", "INFO")
setup_logging(_log_level)

from . import db, auth, match_runner, live_manager

logger = logging.getLogger("finals.app")
FRONTEND_DIST_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    static_folder=os.path.join(FRONTEND_DIST_DIR, "assets"),
    static_url_path="/assets",
)

ADMIN_SECRET = os.environ.get("FINALS_ADMIN_SECRET", "")
BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "bots")
FINALS_SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "snaps", "finals")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# Khởi động
# ---------------------------------------------------------------------------
def startup() -> None:
    logger.info("[APP] Khởi động backend chung kết...")
    db.init()
    db.migrate()
    match_runner.start()
    os.makedirs(FINALS_SNAP_DIR, exist_ok=True)
    logger.info("[APP] Sẵn sàng.")


# ---------------------------------------------------------------------------
# Auth helpers (middleware-like)
# ---------------------------------------------------------------------------
def _get_token() -> str:
    return (
        request.headers.get("X-Finals-Token", "")
        or request.args.get("token", "")
    )


def require_auth():
    token = _get_token()
    user = auth.get_session(token)
    if user is None:
        return jsonify(ok=False, error="Chưa đăng nhập hoặc phiên hết hạn"), 401
    g.current_user = user
    return None


def require_admin():
    # Ban tổ chức xác thực trực tiếp qua Admin Secret (không cần đăng nhập tài khoản thí sinh)
    supplied = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or not secrets.compare_digest(supplied, ADMIN_SECRET):
        logger.warning("[APP] Truy cập admin bị từ chối (Admin Secret không khớp)")
        return jsonify(ok=False, error="Cần quyền ban tổ chức (Vui lòng nhập đúng Admin Secret ở tab Ban Tổ Chức)"), 403
    return None


from werkzeug.exceptions import HTTPException


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jsonify(ok=False, error=e.description), e.code
    code = 400
    if isinstance(e, PermissionError):
        code = 403
    elif isinstance(e, ValueError):
        code = 400
    elif isinstance(e, FileNotFoundError):
        code = 404
    logger.exception("[APP] Lỗi hệ thống: %s", e)
    return jsonify(ok=False, error=str(e)), code


@app.get("/")
@app.get("/finals")
def home():
    """Phục vụ frontend React đã build cho vòng chung kết."""
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return api_info()
    return send_from_directory(FRONTEND_DIST_DIR, "finals.html")


@app.get("/finals/api")
def api_info():
    """Thông tin schema API."""
    return jsonify(
        name="OTT Finals Backend API",
        status="running",
        endpoints={
            "auth": {
                "login": "POST /finals/auth/login",
                "logout": "POST /finals/auth/logout",
                "me": "GET /finals/me",
            },
            "matches": {
                "create": "POST /finals/matches",
                "get_by_request_id": "GET /finals/matches/<request_id>",
                "list": "GET /finals/matches",
            },
            "standings": "GET /finals/standings",
            "admin": {
                "queue": "GET /finals/admin/queue",
                "contestants": "GET /finals/admin/contestants",
                "add_contestant": "POST /finals/admin/contestants",
                "import_finalists": "POST /finals/admin/import-finalists",
                "snapshot_bot": "POST /finals/admin/bots/snapshot",
            },
        },
    ), 200


@app.get("/favicon.ico")
def favicon():
    return "", 204


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@app.post("/finals/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    logger.info("[APP] Login attempt: %s", username)
    token = auth.login(username, password)
    return jsonify(ok=True, token=token), 200


@app.post("/finals/auth/logout")
def logout():
    token = _get_token()
    auth.logout(token)
    return jsonify(ok=True), 200


@app.get("/finals/me")
def me():
    err = require_auth()
    if err:
        return err
    return jsonify(ok=True, user=g.current_user), 200


# ---------------------------------------------------------------------------
# Match endpoints
# ---------------------------------------------------------------------------
@app.post("/finals/matches")
def create_match():
    err = require_admin()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    player_a = data.get("player_a", "").strip()
    player_b = data.get("player_b", "").strip()
    request_id = data.get("request_id")  # tuỳ chọn; nếu không có sẽ tự sinh

    if not player_a or not player_b:
        return jsonify(ok=False, error="Cần cung cấp player_a và player_b"), 400
    if player_a == player_b:
        return jsonify(ok=False, error="Hai thí sinh không được là cùng một người"), 400

    logger.info("[APP] Yêu cầu tạo trận: %s vs %s (request_id=%s)", player_a, player_b, request_id)
    live_delay = data.get("live_delay")
    if live_delay is not None:
        try:
            live_delay = float(live_delay)
        except Exception:
            live_delay = None

    try:
        result = match_runner.enqueue_match(
            player_a, player_b, request_id, snap_dir=FINALS_SNAP_DIR, live_delay=live_delay
        )
    except RuntimeError as e:
        return jsonify(ok=False, error=str(e)), 503

    return jsonify(ok=True, **result), 202


@app.get("/finals/matches/<request_id>")
def get_match(request_id: str):
    row = match_runner.get_match_status(request_id)
    if row is None:
        return jsonify(ok=False, error="Không tìm thấy trận đấu"), 404
    return jsonify(ok=True, match=row), 200


@app.get("/finals/matches/<request_id>/replay")
def get_match_replay(request_id: str):
    row = match_runner.get_match_replay(request_id)
    if row is None:
        return jsonify(ok=False, error="Không tìm thấy trận đấu"), 404
    return jsonify(ok=True, match=row), 200


@app.get("/finals/matches/<request_id>/live")
def match_live_stream(request_id: str):
    """Stream trực tiếp nước đi của trận đấu theo thời gian thực (Server-Sent Events)."""
    def event_generator():
        q = live_manager.subscribe(request_id)
        try:
            yield f"data: {json.dumps({'type': 'connected', 'request_id': request_id})}\n\n"
            while True:
                try:
                    event = q.get(timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("match_end", "match_failed"):
                        break
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            live_manager.unsubscribe(request_id, q)

    return Response(
        event_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/finals/matches")
def list_matches():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 20, type=int)))
    offset = (page - 1) * per_page
    status_filter = request.args.get("status")

    if status_filter:
        rows = db.fetchall(
            """SELECT id, request_id, player_a, player_b, status, score_a, score_b, winner,
                      created_at, started_at, finished_at, error_msg
               FROM matches WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?""",
            (status_filter, per_page, offset),
        )
    else:
        rows = db.fetchall(
            """SELECT id, request_id, player_a, player_b, status, score_a, score_b, winner,
                      created_at, started_at, finished_at, error_msg
               FROM matches ORDER BY id DESC LIMIT ? OFFSET ?""",
            (per_page, offset),
        )
    total = db.fetchone("SELECT count(*) n FROM matches")
    return jsonify(ok=True, matches=rows, total=total["n"], page=page, per_page=per_page), 200


@app.get("/finals/standings")
def get_standings():
    rows = match_runner.standings()
    return jsonify(ok=True, standings=rows), 200


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------
@app.post("/finals/admin/contestants")
def admin_add_contestant():
    err = require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    result = auth.register_contestant(
        username=data.get("username", "").strip(),
        plain_password=data.get("password", ""),
        display_name=data.get("display_name", "").strip(),
        student_id=data.get("student_id"),
    )
    return jsonify(ok=True, contestant=result), 201


@app.get("/finals/admin/contestants")
def admin_list_contestants():
    err = require_admin()
    if err:
        return err
    return jsonify(ok=True, contestants=auth.list_contestants()), 200


@app.post("/finals/admin/import-finalists")
def admin_import_finalists():
    err = require_admin()
    if err:
        return err

    upload = request.files.get("file")
    if upload is None or not upload.filename or not upload.filename.lower().endswith(".csv"):
        return jsonify(ok=False, error="Hãy chọn file CSV finalist đã xuất từ web giải chính."), 400

    try:
        content = upload.stream.read(2 * 1024 * 1024 + 1).decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify(ok=False, error="File CSV phải được mã hóa UTF-8."), 400
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        return jsonify(ok=False, error="File CSV vượt quá giới hạn 2 MB."), 413

    try:
        credentials = auth.import_finalists_csv(content)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    credentials_csv = io.StringIO(newline="")
    columns = ["username", "email", "advance_route", "final_rank", "offline_password"]
    writer = csv.DictWriter(credentials_csv, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for item in credentials:
        writer.writerow({
            "username": item["username"],
            "email": item["email"],
            "advance_route": item["advance_route"],
            "final_rank": item["final_rank"],
            "offline_password": item["password"],
        })
    response = jsonify(
        ok=True,
        imported=len(credentials),
        credentials_csv=credentials_csv.getvalue(),
        contestants=auth.list_contestants(),
    )
    response.headers["Cache-Control"] = "no-store, private"
    return response, 200


@app.delete("/finals/admin/contestants/<username>")
def admin_delete_contestant(username: str):
    err = require_admin()
    if err:
        return err
    auth.delete_contestant(username)
    return jsonify(ok=True), 200


@app.get("/finals/admin/queue")
def admin_queue():
    err = require_admin()
    if err:
        return err
    return jsonify(ok=True, queue=match_runner.get_queue_info()), 200


@app.post("/finals/admin/bots/snapshot")
def admin_snapshot_bot():
    """Copy bot mới nhất của thí sinh vào snaps/finals/ (chốt bot thi chung kết)."""
    err = require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    if not username:
        return jsonify(ok=False, error="Cần cung cấp username"), 400

    src = os.path.join(BOT_DIR, username, "latest.py")
    if not os.path.exists(src):
        return jsonify(ok=False, error=f"Không tìm thấy bot của {username}"), 404

    os.makedirs(FINALS_SNAP_DIR, exist_ok=True)
    import shutil
    dst = os.path.join(FINALS_SNAP_DIR, f"{username}.py")
    shutil.copy2(src, dst)
    logger.info("[APP] Đã snapshot bot: %s → %s", username, dst)
    return jsonify(ok=True, saved=dst), 200


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    startup()
    port = int(os.environ.get("FINALS_PORT", 9000))
    logger.info("[APP] Chạy trên cổng %d", port)
    app.run(host="0.0.0.0", port=port, threaded=True)
