"""Server nhận bài. Chạy: pip install flask && python server.py
Thí sinh KHÔNG bao giờ xem được code của nhau: không có endpoint nào trả về nội dung bài nộp.

POST /register   json {"name": "abc"}                -> {"token": "..."}   (giữ kín token)
POST /submit     header X-Token, form file=@bot.py    -> {"ok": true}
GET  /me         header X-Token                       -> trạng thái, bảng, thứ hạng các ngày
GET  /leaderboard header X-Token  [?day=3]            -> BXH bảng của mình (ngày mới nhất đã chấm)

Admin rule API:
GET  /admin/api/rules                              -> luật đã chọn và trạng thái từng vòng
POST /admin/api/rules json {"round": 2, "rule": "rule3.json"}
"""
import json
import os
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import wraps

from flask import Flask, request, jsonify, render_template, send_file, send_from_directory, session, redirect, url_for
import tournament as T

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("ADMIN_PASSWORD")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
T.init()
T.publish_live_tournament_snapshot()

_admin_executor = ThreadPoolExecutor(max_workers=1)
_admin_job_lock = threading.Lock()
_admin_job = None


@app.get("/")
def home():
    """Giao diện web cho người chơi."""
    return render_template("index.html")


@app.get("/live")
def live_tournament():
    return render_template("live.html")


@app.get("/live-board.json")
def live_tournament_board():
    response = send_file(
        T.LIVE_BOARD_SNAPSHOT,
        mimetype="application/json",
        conditional=True,
        max_age=20,
    )
    response.headers["Cache-Control"] = (
        "public, max-age=10, s-maxage=20, stale-while-revalidate=40"
    )
    return response


@app.get("/sample_bot.py")
def sample_bot():
    """Cho thí sinh xem mã nguồn bot mẫu."""
    return send_from_directory(app.root_path, "sample_bot.py", mimetype="text/plain")


def csrf_token():
    return session.setdefault("csrf_token", secrets.token_urlsafe(32))


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify(ok=False, error="Cần đăng nhập ban tổ chức"), 401
        if request.method != "GET":
            supplied = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf_token", "")
            if not expected or not secrets.compare_digest(supplied, expected):
                return jsonify(ok=False, error="Phiên thao tác hết hạn. Hãy tải lại trang admin."), 403
        return fn(*args, **kwargs)
    return wrapped


@app.route("/admin", methods=["GET", "POST"])
def admin():
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        return render_template("admin_login.html", configured=False, error=None, csrf=None), 503
    if request.method == "POST":
        expected = csrf_token()
        supplied = request.form.get("csrf_token", "")
        if not secrets.compare_digest(supplied, expected):
            return render_template("admin_login.html", configured=True,
                                   error="Phiên đăng nhập hết hạn. Hãy tải lại trang.",
                                   csrf=expected), 403
        if not secrets.compare_digest(request.form.get("password", ""), password):
            return render_template("admin_login.html", configured=True,
                                   error="Mật khẩu quản trị không đúng.", csrf=expected), 401
        session.clear()
        session["is_admin"] = True
        session.permanent = True
        csrf_token()
        return redirect(url_for("admin"))
    if session.get("is_admin"):
        return render_template("admin.html", csrf=csrf_token())
    return render_template("admin_login.html", configured=True, error=None, csrf=csrf_token())


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/admin/api/overview")
@admin_required
def admin_overview():
    return jsonify(T.admin_overview())


@app.get("/admin/api/rules")
@admin_required
def admin_rules():
    return jsonify(T.round_rule_settings())


@app.post("/admin/api/rules")
@admin_required
def set_admin_round_rule():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Nội dung gửi lên phải là JSON object."), 400
    rnd, filename = payload.get("round"), payload.get("rule")
    if type(rnd) is not int or not isinstance(filename, str):
        return jsonify(
            ok=False,
            error="Cần gửi round dạng số nguyên và rule dạng tên file.",
        ), 400
    with _admin_job_lock:
        if _admin_job and _admin_job["state"] == "running":
            return jsonify(
                ok=False,
                error="Không thể đổi luật khi đang chạy thao tác quản trị.",
            ), 409
        try:
            settings = T.set_round_rule(rnd, filename)
        except RuntimeError as exc:
            return jsonify(ok=False, error=str(exc)), 409
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
    return jsonify(ok=True, **settings)


@app.get("/champion")
def champion():
    return jsonify(champion=T.get("champion"))


@app.get("/live-leaderboard")
def live_leaderboard():
    return jsonify(T.live_leaderboard())


@app.get("/admin/api/job")
@admin_required
def admin_job_status():
    with _admin_job_lock:
        return jsonify(_admin_job or {"state": "idle"})


def start_admin_job(action, work):
    global _admin_job
    with _admin_job_lock:
        if _admin_job and _admin_job["state"] == "running":
            return jsonify(ok=False, error="Một thao tác quản trị khác đang chạy."), 409
        job_id = uuid.uuid4().hex
        _admin_job = {"id": job_id, "action": action, "state": "running"}
        _admin_executor.submit(run_admin_job, job_id, work)
    return jsonify(ok=True, job_id=job_id), 202


def run_admin_job(job_id, work):
    global _admin_job
    try:
        result = work()
    except (Exception, SystemExit) as exc:
        with _admin_job_lock:
            if _admin_job and _admin_job["id"] == job_id:
                _admin_job = {"id": job_id, "action": _admin_job["action"],
                              "state": "failed", "error": f"{type(exc).__name__}: {exc}"}
                if _admin_job["action"] == "Chấm ngày thi và xét lên vòng nếu là ngày cuối":
                    try:
                        progress = json.loads(T.get("live_scoring", "{}"))
                        if progress:
                            progress["state"] = "failed"
                            progress["error"] = f"{type(exc).__name__}: {exc}"
                            T.put("live_scoring", json.dumps(progress))
                            T.publish_live_tournament_snapshot()
                    except (ValueError, TypeError):
                        app.logger.exception("Could not record live scoring failure")
        app.logger.exception("Admin operation %s failed", job_id)
        return
    with _admin_job_lock:
        if _admin_job and _admin_job["id"] == job_id:
            _admin_job = {"id": job_id, "action": _admin_job["action"],
                          "state": "complete", "result": result}


def run_entry_close():
    T.put("accepting_submissions", 0)
    T.entry_close()
    T.put("accepting_submissions", 1)
    return T.admin_overview()


def run_close_day():
    T.put("accepting_submissions", 0)
    T.close_day()
    T.put("accepting_submissions", 1)
    return T.admin_overview()


def run_tournament_grade():
    T.grade_day()


def run_tournament_reset():
    T.reset_tournament()
    T.publish_live_tournament_snapshot()
    return T.admin_overview()


def tournament_reset_running():
    return (
        _admin_job
        and _admin_job["state"] == "running"
        and _admin_job["action"] == "Reset toàn bộ cuộc thi"
    )


@app.post("/admin/api/actions/<action>")
@admin_required
def admin_action(action):
    overview = T.admin_overview()
    if action == "reset":
        return start_admin_job("Reset toàn bộ cuộc thi", run_tournament_reset)
    if action == "entry-close":
        if overview["phase"] != "entry":
            return jsonify(ok=False, error="Chỉ có thể chấm đầu vào khi giải đang ở giai đoạn entry."), 409
        return start_admin_job("Chấm đầu vào và chia bảng", run_entry_close)
    if action == "close-day":
        if overview["phase"] != "round" or overview["pending"]:
            return jsonify(ok=False, error="Chỉ có thể chốt ngày thi khi đang ở vòng và không có ngày chờ chấm."), 409
        return start_admin_job("Chốt bài nộp ngày thi", run_close_day)
    if action == "grade-day":
        if overview["phase"] != "round" or not overview["pending"]:
            return jsonify(ok=False, error="Không có ngày thi đang chờ chấm."), 409
        return start_admin_job("Chấm ngày thi và xét lên vòng nếu là ngày cuối", run_tournament_grade)
    return jsonify(ok=False, error="Thao tác quản trị không hợp lệ."), 404


@app.post("/admin/api/submissions")
@admin_required
def admin_submissions():
    payload = request.get_json(silent=True) or {}
    accepting = payload.get("accepting")
    if not isinstance(accepting, bool):
        return jsonify(ok=False, error="Trường accepting phải là true hoặc false."), 400
    if T.get("phase", "entry") == "done" and accepting:
        return jsonify(ok=False, error="Giải đã kết thúc, không thể mở nhận bài."), 409
    with _admin_job_lock:
        if _admin_job and _admin_job["state"] == "running":
            return jsonify(ok=False, error="Không thể đổi trạng thái nhận bài khi đang chạy thao tác khác."), 409
        T.put("accepting_submissions", int(accepting))
        return jsonify(T.admin_overview())


@app.post("/admin/api/live-scores")
@admin_required
def admin_live_scores():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Nội dung gửi lên phải là JSON object."), 400
    try:
        records = T.save_live_scores(payload.get("event"), payload.get("scores"))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400

    return jsonify(ok=True, saved=len(records)), 201


def auth():
    u = T.user_by_token(request.headers.get("X-Token"))
    if not u:
        raise PermissionError("Sai token")
    return u["name"]


@app.errorhandler(Exception)
def err(e):
    code = 403 if isinstance(e, PermissionError) else 400
    return jsonify(ok=False, error=str(e)), code


@app.post("/register")
def register():
    with _admin_job_lock:
        if tournament_reset_running():
            return jsonify(ok=False, error="Cuộc thi đang được reset. Vui lòng thử lại sau."), 503
        return jsonify(token=T.register((request.get_json(silent=True) or {}).get("name", "")))


@app.post("/submit")
def submit():
    f = request.files.get("file")
    if not f:
        raise ValueError("Thiếu file")
    with _admin_job_lock:
        if tournament_reset_running():
            return jsonify(ok=False, error="Cuộc thi đang được reset. Vui lòng thử lại sau."), 503
        name = auth()
        T.submit(name, f.read())
        return jsonify(ok=True)


@app.get("/me")
def me():
    return jsonify(T.my_status(auth()))


@app.get("/leaderboard")
def lb():
    day = request.args.get("day", type=int)
    return jsonify(T.leaderboard(auth(), day))


@app.get("/replays")
def match_replays():
    rnd = request.args.get("round", type=int)
    day = request.args.get("day", type=int)
    return jsonify(T.replays(auth(), rnd, day))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
