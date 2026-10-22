"""Storage server chạy trên máy local, mở ra Internet qua Cloudflare Tunnel (xem CLOUDFLARE_TUNNEL.md).

Chỉ phục vụ replay đã chấm. Quyền xem do Supabase quyết định: JWT của người dùng được chuyển tới
RPC `get_replay_ref` (chạy dưới RLS); không có dòng trả về = không được xem. Code bot KHÔNG bao giờ được phục vụ.

  GET /healthz
  GET /replays/<match_id>   Authorization: Bearer <access_token>   -> JSON ván đấu (gzip)

Chạy:  python -m data.storage_server            (dev)
       waitress-serve --listen=127.0.0.1:8100 data.storage_server:app   (thật)
"""
from flask import Flask, Response, jsonify, request

from . import config, replay_store
from .supabase_client import Supabase, SupabaseError

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024
_sb = None


def sb():
    global _sb
    if _sb is None:
        _sb = Supabase()
    return _sb


@app.after_request
def cors(resp):
    origin = request.headers.get("Origin")
    if origin and ("*" in config.CORS_ORIGINS or origin in config.CORS_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/replays/<int:match_id>", methods=["OPTIONS"])
def preflight(match_id):
    return "", 204


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.get("/replays/<int:match_id>")
def get_replay(match_id):
    h = request.headers.get("Authorization", "")
    token = h[7:].strip() if h.lower().startswith("bearer ") else ""
    if not token:
        return jsonify(ok=False, error="Chưa đăng nhập"), 401
    try:
        ref = sb().rpc("get_replay_ref", {"p_match_id": match_id}, token=token)
    except SupabaseError as e:
        return jsonify(ok=False, error="Phiên đăng nhập không hợp lệ"), 401 if e.status in (401, 403) else 502
    if not ref:                                   # không cùng bảng / chưa chấm xong / không tồn tại
        return jsonify(ok=False, error="Không tìm thấy replay"), 404
    r = ref[0]
    raw = replay_store.read_gz_bytes(r["rnd"], r["day"], r["grp"], r["rd"], r["player_a"], r["player_b"])
    if raw is None:
        return jsonify(ok=False, error="Replay chưa có trên máy chủ"), 404
    return Response(raw, mimetype="application/json", headers={
        "Content-Encoding": "gzip", "Cache-Control": "private, max-age=3600"})


@app.errorhandler(404)
def not_found(e):
    import sys
    print(f"\n[STORAGE_SERVER CẢNH BÁO] Phát hiện request: {request.method} {request.path} trên Storage Server (port 8100)!\n"
          f"       LƯU Ý: Server port 8100 này chỉ là Storage Server phục vụ Replay (xem CLOUDFLARE_TUNNEL.md).\n"
          f"       Server nộp bài, đăng nhập & chấm thi là server.py (chạy trên port 8000)!\n", file=sys.stderr, flush=True)
    if request.path.startswith("/submit") or request.path.startswith("/test-bot"):
        return jsonify(ok=False, error="Bạn đang gửi bài vào Storage Server (port 8100)! Hãy kiểm tra lại: Server nộp bài là server.py (port 8000)."), 404
    return jsonify(ok=False, error=f"Endpoint không tồn tại trên Storage Server: {request.path}"), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(config.env("OTT_STORAGE_PORT", "8100")))
