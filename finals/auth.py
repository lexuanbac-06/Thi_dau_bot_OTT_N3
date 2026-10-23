"""
finals/auth.py
--------------
Login / logout / session management cho vòng chung kết.
Dùng bcrypt hash password và session token ngẫu nhiên.
"""
import csv
import io
import logging
import re
import secrets
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


def import_finalists_csv(content: str) -> list[dict]:
    """Import a round-four roster and issue fresh, local-only passwords."""
    if not content.strip():
        raise ValueError("Chưa có danh sách thí sinh đủ điều kiện chung kết.")
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("File CSV vượt quá giới hạn 2 MB.")

    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    required_columns = {"user_id", "username", "email", "advance_route", "final_rank"}
    if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
        raise ValueError("CSV thiếu cột bắt buộc. Hãy xuất lại CSV finalist từ web giải chính.")

    normalized: list[dict[str, str]] = []
    seen_ids = set()
    seen_names = set()
    seen_emails = set()
    for line_number, finalist in enumerate(reader, start=2):
        user_id = str(finalist.get("user_id") or "").strip()
        username = str(finalist.get("username") or "").strip()
        email = str(finalist.get("email") or "").strip()
        route = str(finalist.get("advance_route") or "").strip()
        final_rank = str(finalist.get("final_rank") or "").strip()
        avg_rank_pct = str(finalist.get("avg_rank_pct") or "").strip()
        if not user_id or not username or not email or route not in {"top", "wildcard"}:
            raise ValueError(f"Dữ liệu finalist không hợp lệ ở dòng {line_number}.")
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            raise ValueError(f"Username không hợp lệ ở dòng {line_number}.")
        if not final_rank.isdigit() or int(final_rank) < 1:
            raise ValueError(f"Thứ hạng không hợp lệ ở dòng {line_number}.")
        if user_id in seen_ids or username.casefold() in seen_names or email.casefold() in seen_emails:
            raise ValueError("Danh sách chung kết có tài khoản bị trùng.")
        seen_ids.add(user_id)
        seen_names.add(username.casefold())
        seen_emails.add(email.casefold())
        normalized.append({
            "user_id": user_id,
            "username": username,
            "email": email,
            "advance_route": route,
            "final_rank": final_rank,
            "avg_rank_pct": avg_rank_pct,
        })
    if not normalized:
        raise ValueError("CSV không có thí sinh nào.")

    issued_credentials = []
    with db.conn() as connection:
        for finalist in normalized:
            existing_rows = connection.execute(
                """SELECT username, auth_user_id FROM contestants
                   WHERE username = ? COLLATE NOCASE
                      OR auth_user_id = ?
                      OR email = ? COLLATE NOCASE""",
                (finalist["username"], finalist["user_id"], finalist["email"]),
            ).fetchall()
            if any(
                existing["username"] != finalist["username"]
                or existing["auth_user_id"] != finalist["user_id"]
                for existing in existing_rows
            ):
                raise ValueError(
                    f"Tài khoản {finalist['username']} xung đột với tài khoản chung kết đã có; "
                    "không có dữ liệu nào được đồng bộ."
                )

        for finalist in normalized:
            password = secrets.token_urlsafe(12)
            connection.execute(
                """INSERT INTO contestants(
                       username, password, display_name, auth_user_id, email,
                       advance_route, final_rank, avg_rank_pct
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(username) DO UPDATE SET
                       password = excluded.password,
                       display_name = excluded.display_name,
                       auth_user_id = excluded.auth_user_id,
                       email = excluded.email,
                       advance_route = excluded.advance_route,
                       final_rank = excluded.final_rank,
                       avg_rank_pct = excluded.avg_rank_pct""",
                (
                    finalist["username"],
                    hash_password(password),
                    finalist["username"],
                    finalist["user_id"],
                    finalist["email"],
                    finalist["advance_route"],
                    int(finalist["final_rank"]),
                    finalist["avg_rank_pct"] or None,
                ),
            )
            issued_credentials.append({
                "username": finalist["username"],
                "email": finalist["email"],
                "advance_route": finalist["advance_route"],
                "final_rank": int(finalist["final_rank"]),
                "password": password,
            })
        connection.commit()
    logger.info("[AUTH] Nhập %d finalist và cấp mật khẩu offline", len(normalized))
    return issued_credentials


def login(username: str, plain_password: str) -> str:
    """Kiểm tra thông tin đăng nhập, trả về session token nếu hợp lệ."""
    row = db.fetchone(
        """SELECT username, password, display_name
           FROM contestants
           WHERE username = ? COLLATE NOCASE
           LIMIT 1""",
        (username,),
    )
    if row is None:
        logger.warning("[AUTH] Đăng nhập thất bại: %s", username)
        raise PermissionError("Sai tên đăng nhập hoặc mật khẩu")
    if not check_password(plain_password, row["password"]):
        logger.warning("[AUTH] Đăng nhập thất bại: %s", username)
        raise PermissionError("Sai tên đăng nhập hoặc mật khẩu")

    token = secrets.token_hex(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    db.execute(
        "INSERT INTO sessions(token, username, expires_at) VALUES (?, ?, ?)",
        (token, row["username"], expires),
    )
    logger.info("[AUTH] Đăng nhập thành công: %s", row["username"])
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
