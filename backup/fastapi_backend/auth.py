import asyncio
from typing import Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .supabase_client import get_supabase, SupabaseError

security = HTTPBearer(auto_error=False)

def get_profile(user_id: str, token: str, user_meta: dict = None) -> dict:
    sb = get_supabase()
    rows = sb.select("profiles", {"id": f"eq.{user_id}", "limit": "1"})
    
    if rows:
        profile = rows[0]
    else:
        # Dự phòng nếu trigger handle_new_user chưa chạy kịp
        username = (user_meta or {}).get("username") or f"user_{user_id[:8]}"
        try:
            inserted = sb.insert("profiles", [{"id": user_id, "username": username}])
            profile = inserted[0] if inserted else {"id": user_id, "username": username, "role": "contestant", "status": "new"}
        except Exception:
            profile = {"id": user_id, "username": username, "role": "contestant", "status": "new"}

    return profile

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> dict:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa cung cấp token xác thực (Authorization: Bearer <token>).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    sb = get_supabase()
    try:
        sb_user = await asyncio.to_thread(sb.get_user, token)
    except (SupabaseError, Exception) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = sb_user.get("id")
    email = sb_user.get("email")
    user_metadata = sb_user.get("user_metadata", {})
    
    profile = await asyncio.to_thread(get_profile, user_id, token, user_metadata)
    username = profile.get("username") or user_metadata.get("username") or email.split("@")[0]
    role = profile.get("role", "contestant")
    user_status = profile.get("status", "new")

    return {
        "id": user_id,
        "email": email,
        "username": username,
        "role": role,
        "status": user_status,
        "token": token,
    }

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản không có quyền Admin (Ban tổ chức).",
        )
    return user
