import csv
import io
import re
from typing import List, Dict, Any
from .supabase_client import get_supabase, SupabaseError
from . import config

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def validate_admin_input(email: str, username: str, password: str):
    email = email.strip()
    username = username.strip()
    if not EMAIL_RE.match(email):
        raise ValueError(f"Email không hợp lệ: '{email}'")
    if not USERNAME_RE.match(username):
        raise ValueError(f"Username '{username}' phải từ 3-20 ký tự (chữ, số hoặc dấu gạch dưới)")
    if len(password) < config.MIN_PASSWORD_LEN:
        raise ValueError(f"Mật khẩu quá ngắn (tối thiểu {config.MIN_PASSWORD_LEN} ký tự)")
    if len(password) > 72:
        raise ValueError("Mật khẩu tối đa 72 ký tự (giới hạn bcrypt)")
    return email, username, password

def create_admin_account(email: str, username: str, password: str) -> Dict[str, Any]:
    email, username, password = validate_admin_input(email, username, password)
    sb = get_supabase()

    # Tạo user trong Supabase Auth bằng Admin API (service_role key), email_confirm=True
    created = sb.admin_create_user(email=email, password=password, username=username, email_confirm=True)
    uid = created["id"]

    try:
        # Cập nhật quyền admin trong bảng profiles
        sb.update("profiles", {"id": f"eq.{uid}"}, {"role": "admin"})
    except Exception as exc:
        # Nếu lỗi thì rollback xóa user Supabase
        try:
            sb.admin_delete_user(uid)
        except Exception:
            pass
        raise exc

    return {"id": uid, "email": email, "username": username, "role": "admin"}

def import_admins_from_csv(csv_content: str) -> Dict[str, Any]:
    f = io.StringIO(csv_content.strip())
    reader = csv.reader(f)
    
    created = []
    errors = []
    
    for row_idx, row in enumerate(reader, start=1):
        if not row:
            continue
        # Bỏ qua dòng tiêu đề nếu có
        first_cell = row[0].strip().lower()
        if first_cell in ("email", "e-mail", "username"):
            continue
        
        if len(row) < 3:
            errors.append({
                "row": row_idx,
                "data": row,
                "error": "Dòng thiếu cột (cần đủ: email, username, password)"
            })
            continue

        email, username, password = row[0].strip(), row[1].strip(), row[2].strip()
        try:
            res = create_admin_account(email, username, password)
            created.append(res)
        except (ValueError, SupabaseError, Exception) as exc:
            errors.append({
                "row": row_idx,
                "email": email,
                "username": username,
                "error": str(exc)
            })

    return {
        "success_count": len(created),
        "error_count": len(errors),
        "created": created,
        "errors": errors
    }

if __name__ == "__main__":
    create_admin_account("admin@ott.vn", "admin", "admin@ott.vn")
