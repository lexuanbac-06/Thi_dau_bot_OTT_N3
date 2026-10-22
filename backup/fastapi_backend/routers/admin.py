import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..admin_service import create_admin_account, import_admins_from_csv
from ..auth import require_admin

logger = logging.getLogger("admin_router")
router = APIRouter(tags=["Admin"])


class CreateAdminPayload(BaseModel):
    email: str
    username: str
    password: str


@router.post("/api/admin/create-admin")
async def api_create_admin(payload: CreateAdminPayload, _admin: dict = Depends(require_admin)):
    try:
        result = await asyncio.to_thread(
            create_admin_account, str(payload.email), payload.username, payload.password
        )
        return {"ok": True, "admin": result}
    except Exception as exc:
        logger.exception("Admin account creation failed")
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/api/admin/import-admins")
async def api_import_admins(file: UploadFile = File(...), _admin: dict = Depends(require_admin)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Vui lòng tải lên file CSV (.csv)")
    content = await file.read(1_000_001)
    if len(content) > 1_000_000:
        raise HTTPException(status_code=413, detail="File CSV vượt quá 1 MB")
    result = await asyncio.to_thread(
        import_admins_from_csv, content.decode("utf-8", errors="replace")
    )
    return {"ok": True, "result": result}


@router.get("/api/admin/sample-csv")
async def get_sample_csv(_admin: dict = Depends(require_admin)):
    return {
        "ok": True,
        "content": "email,username,password\nadmin1@example.com,admin_alpha,SecureAdmin@123456\n",
        "filename": "admins_sample.csv",
    }
