"""Đăng ký / đăng nhập / đăng xuất bằng Supabase Auth.

Thí sinh dùng username + mật khẩu; backend ánh xạ username -> email giả `<username>@OTT_EMAIL_DOMAIN`.
Mọi tài khoản đều có 1 dòng `users` trong ott.db (SQLite) để engine chấm điểm dùng chung khóa tên.

Flask blueprint `auth_bp` (gắn vào server.py):
  POST /auth/register {"username","password"} -> {"ok",username,"legacy_token"}
  POST /auth/login    {"username","password"} -> {"access_token","refresh_token","expires_in","user"}
  POST /auth/refresh  {"refresh_token"}       -> token mới
  POST /auth/logout   Authorization: Bearer   -> {"ok"}
  GET  /auth/me       Authorization: Bearer   -> {"user"}
"""
import hashlib
import re
import threading
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request

from . import config
from .supabase_client import Supabase, SupabaseError

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,20}")
_sb = None


def sb():
    global _sb
    if _sb is None:
        _sb = Supabase()
    return _sb


def username_to_email(username):
    return f"{username.lower()}@{config.EMAIL_DOMAIN}"


def _now():
    return datetime.now(timezone.utc).isoformat()


def validate_credentials(username, password):
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        raise ValueError("Tên 3-20 ký tự A-Z a-z 0-9 _")
    if not isinstance(password, str) or len(password) < config.MIN_PASSWORD_LEN:
        raise ValueError(f"Mật khẩu tối thiểu {config.MIN_PASSWORD_LEN} ký tự")
    if len(password) > 72:                                  # giới hạn bcrypt
        raise ValueError("Mật khẩu tối đa 72 ký tự")


def log_event(event, user_id=None, username=None, ip=None, ua=None):
    try:
        sb().insert("auth_events", [{
            "event": event, "user_id": user_id, "username": username,
            "ip": ip, "user_agent": (ua or "")[:300]}])
    except Exception:                                       # nhật ký không được làm hỏng đăng nhập
        pass


def _ensure_local_user(username):
    """Tạo dòng users trong ott.db nếu chưa có; trả token cũ (legacy) nếu vừa tạo."""
    import tournament as T
    if T.q("select 1 from users where name=?", (username,)):
        return None
    return T.register(username)


ensure_local_user = _ensure_local_user


def create_account(username, password, admin=False, ip=None, ua=None):
    """Tạo user Supabase + user local. Rollback Supabase nếu bước local lỗi."""
    validate_credentials(username, password)
    created = sb().admin_create_user(username_to_email(username), password, username)
    uid = created["id"]
    try:
        legacy = _ensure_local_user(username)
        if admin:
            sb().update("profiles", {"id": f"eq.{uid}"}, {"role": "admin"})
    except Exception:
        try:
            sb().admin_delete_user(uid)
        except Exception:
            pass                                            # giữ nguyên lỗi gốc
        raise
    log_event("register", uid, username, ip, ua)
    return {"id": uid, "username": username, "legacy_token": legacy}


# ---------------- Giới hạn thử mật khẩu sai (trong bộ nhớ, 1 worker) ----------------
_fails, _fails_lock = {}, threading.Lock()
MAX_FAILS, WINDOW = 8, 300


def _throttled(key):
    with _fails_lock:
        hits = [t for t in _fails.get(key, []) if time.time() - t < WINDOW]
        _fails[key] = hits
        return len(hits) >= MAX_FAILS


def _fail(key):
    with _fails_lock:
        _fails.setdefault(key, []).append(time.time())


def login(username, password, ip=None, ua=None):
    key = f"{ip}|{str(username).lower()}"
    if _throttled(key):
        raise PermissionError("Thử sai quá nhiều lần, vui lòng đợi vài phút")
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username) or not isinstance(password, str):
        raise PermissionError("Sai tên hoặc mật khẩu")
    try:
        s = sb().sign_in(username_to_email(username), password)
    except SupabaseError as e:
        if e.status in (400, 401, 422):
            _fail(key)
            log_event("login_failed", None, username, ip, ua)
            raise PermissionError("Sai tên hoặc mật khẩu") from None
        raise
    uid = s["user"]["id"]
    prof = sb().select("profiles", {"id": f"eq.{uid}", "select": "username,role,status"})
    if not prof:
        raise PermissionError("Tài khoản chưa có hồ sơ")
    if prof[0]["status"] == "banned":
        raise PermissionError("Tài khoản đã bị khóa")
    sb().update("profiles", {"id": f"eq.{uid}"}, {"last_login_at": _now()})
    log_event("login", uid, prof[0]["username"], ip, ua)
    return {"access_token": s["access_token"], "refresh_token": s["refresh_token"],
            "expires_in": s["expires_in"], "user": {"id": uid, **prof[0]}}


def refresh(refresh_token):
    try:
        s = sb().refresh(refresh_token)
    except SupabaseError:
        raise PermissionError("Phiên đăng nhập hết hạn") from None
    return {"access_token": s["access_token"], "refresh_token": s["refresh_token"],
            "expires_in": s["expires_in"]}


_cache, _cache_lock = {}, threading.Lock()
CACHE_TTL = 30


def verify_token(access_token):
    """Kiểm tra JWT với Supabase (đã tính cả logout/thu hồi), cache 30 giây. Trả profile hoặc PermissionError."""
    if not access_token:
        raise PermissionError("Chưa đăng nhập")
    k = hashlib.sha256(access_token.encode()).hexdigest()
    with _cache_lock:
        hit = _cache.get(k)
        if hit and hit[0] > time.time():
            return hit[1]
    try:
        u = sb().get_user(access_token)
        prof = sb().select("profiles", {"id": f"eq.{u['id']}", "select": "id,username,role,status"})
    except SupabaseError:
        raise PermissionError("Phiên đăng nhập không hợp lệ") from None
    if not prof or prof[0]["status"] == "banned":
        raise PermissionError("Tài khoản không khả dụng")
    with _cache_lock:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[k] = (time.time() + CACHE_TTL, prof[0])
    return prof[0]


def logout(access_token, ip=None, ua=None):
    prof = verify_token(access_token)
    try:
        sb().sign_out(access_token, scope="global")
    except SupabaseError:
        pass
    with _cache_lock:
        _cache.pop(hashlib.sha256(access_token.encode()).hexdigest(), None)
    sb().update("profiles", {"id": f"eq.{prof['id']}"}, {"last_logout_at": _now()})
    log_event("logout", prof["id"], prof["username"], ip, ua)


# ---------------- Flask ----------------
auth_bp = Blueprint("data_auth", __name__, url_prefix="/auth")


def bearer():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def _client():
    return request.headers.get("CF-Connecting-IP") or request.remote_addr, request.headers.get("User-Agent")


def login_required(admin=False):
    def deco(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            try:
                prof = verify_token(bearer())
            except PermissionError as e:
                return jsonify(ok=False, error=str(e)), 401
            if admin and prof["role"] != "admin":
                return jsonify(ok=False, error="Cần quyền ban tổ chức"), 403
            request.user = prof
            return fn(*a, **kw)
        return wrapped
    return deco


@auth_bp.post("/register")
def http_register():
    if not config.OPEN_REGISTRATION:
        return jsonify(ok=False, error="Đăng ký đang đóng"), 403
    p = request.get_json(silent=True) or {}
    ip, ua = _client()
    try:
        r = create_account(p.get("username"), p.get("password"), ip=ip, ua=ua)
    except SupabaseError as e:
        dup = e.status in (409, 422) and "regist" in str(e).lower()
        return jsonify(ok=False, error="Tên đã tồn tại" if dup else "Không tạo được tài khoản"), 409 if dup else 400
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, username=r["username"], legacy_token=r["legacy_token"]), 201


@auth_bp.post("/login")
def http_login():
    p = request.get_json(silent=True) or {}
    ip, ua = _client()
    try:
        return jsonify(ok=True, **login(p.get("username"), p.get("password"), ip, ua))
    except PermissionError as e:
        return jsonify(ok=False, error=str(e)), 401


@auth_bp.post("/refresh")
def http_refresh():
    try:
        return jsonify(ok=True, **refresh((request.get_json(silent=True) or {}).get("refresh_token", "")))
    except PermissionError as e:
        return jsonify(ok=False, error=str(e)), 401


@auth_bp.post("/logout")
@login_required()
def http_logout():
    ip, ua = _client()
    logout(bearer(), ip, ua)
    return jsonify(ok=True)


@auth_bp.get("/me")
@login_required()
def http_me():
    return jsonify(ok=True, user=request.user)
