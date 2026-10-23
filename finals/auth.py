"""
finals/auth.py
--------------
Login / logout / session management cho vòng chung kết.
Dùng bcrypt hash password và session token ngẫu nhiên.
"""
import logging
import secrets
import time
from datetime import datetime, timezone, timedelta

import bcrypt

from . import db

logger = logging.getLogger("finals.auth")

SESSION_TTL_HOURS = 8


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def check_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Quản lý sinh viên
# ---------------------------------------------------------------------------
def register_contestant(username: str, plain_password: str, display_name: str, student_id: str | None = None) -> dict:
    """Đăng ký sinh viên mới. Raise ValueError nếu username/student_id đã tồn tại."""
    if not username or len(username) < 3:
        raise ValueError("username phải có ít nhất 3 ký tự")
    if not plain_password or len(plain_password) < 6:
        raise ValueError("Mật khẩu phải có ít nhất 6 ký tự")

    hashed = hash_password(plain_password)
    try:
        db.execute(
            """INSERT INTO contestants(username, password, display_name, student_id)
               VALUES (?, ?, ?, ?)""",
            (username, hashed, display_name, student_id),
        )
    except Exception as e:
        msg = str(e)
        if "unique" in msg.lower():
            raise ValueError("Username hoặc MSSV đã tồn tại")
        raise

    logger.info("[AUTH] Đăng ký thành công: %s (%s)", username, display_name)
    return {"username": username, "display_name": display_name, "student_id": student_id}


def login(username: str, plain_password: str) -> str:
    """Kiểm tra thông tin đăng nhập, trả về session token nếu hợp lệ."""
    row = db.fetchone(
        "SELECT password, display_name FROM contestants WHERE username=?",
        (username,),
    )
    if row is None or not check_password(plain_password, row["password"]):
        logger.warning("[AUTH] Đăng nhập thất bại: %s", username)
        raise PermissionError("Sai tên đăng nhập hoặc mật khẩu")

    token = secrets.token_hex(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    db.execute(
        "INSERT INTO sessions(token, username, expires_at) VALUES (?, ?, ?)",
        (token, username, expires),
    )
    logger.info("[AUTH] Đăng nhập thành công: %s", username)
    return token


def logout(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token=?", (token,))
    logger.info("[AUTH] Đăng xuất token ...%s", token[-8:])


def get_session(token: str) -> dict | None:
    """Trả về thông tin contestant nếu token hợp lệ và chưa hết hạn."""
    if not token:
        return None
    row = db.fetchone(
        """SELECT s.username, c.display_name, c.student_id
           FROM sessions s JOIN contestants c USING(username)
           WHERE s.token=? AND datetime(s.expires_at) > CURRENT_TIMESTAMP""",
        (token,),
    )
    return row  # None nếu không tìm thấy


def purge_expired_sessions() -> int:
    """Xoá session đã hết hạn (dùng cho maintenance job định kỳ)."""
    with db.conn() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE datetime(expires_at) <= CURRENT_TIMESTAMP")
            n = cur.rowcount
        c.commit()
    if n:
        logger.info("[AUTH] Đã xoá %d session hết hạn", n)
    return n


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------
def list_contestants() -> list[dict]:
    return db.fetchall(
        "SELECT username, display_name, student_id, created_at FROM contestants ORDER BY username"
    )


def delete_contestant(username: str) -> None:
    db.execute("DELETE FROM contestants WHERE username=?", (username,))
    logger.info("[AUTH] Xoá sinh viên: %s", username)
