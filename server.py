"""Server nhận bài. Chạy: pip install flask && python server.py
Thí sinh KHÔNG bao giờ xem được code của nhau: không có endpoint nào trả về nội dung bài nộp.

POST /register   json {"name": "abc"}                -> {"token": "..."}   (giữ kín token)
POST /submit     header X-Token, form file=@bot.py    -> {"ok": true}
GET  /me         header X-Token                       -> trạng thái, bảng, thứ hạng các ngày
GET  /leaderboard header X-Token  [?day=3]            -> BXH bảng của mình (ngày mới nhất đã chấm)
"""
from flask import Flask, request, jsonify, render_template, send_from_directory
import tournament as T

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 70 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True
T.init()


@app.get("/")
def home():
    """Giao diện web cho người chơi."""
    return render_template("index.html")


@app.get("/sample_bot.py")
def sample_bot():
    """Cho thí sinh xem mã nguồn bot mẫu."""
    return send_from_directory(app.root_path, "sample_bot.py", mimetype="text/plain")


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
    return jsonify(token=T.register((request.get_json(silent=True) or {}).get("name", "")))


@app.post("/submit")
def submit():
    name = auth()
    f = request.files.get("file")
    if not f:
        raise ValueError("Thiếu file")
    T.submit(name, f.read())
    return jsonify(ok=True)


@app.get("/me")
def me():
    return jsonify(T.my_status(auth()))


@app.get("/leaderboard")
def lb():
    day = request.args.get("day", type=int)
    return jsonify(T.leaderboard(auth(), day))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
