import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import config
from .routers import admin

app = FastAPI(
    title="OTT Arena Backend API",
    version="2.0.0",
    description="API quản trị nhẹ cho OTT Arena",
)

# Cấu hình CORS cho frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Các truy vấn thi đấu/leaderboard đi trực tiếp tới Supabase từ frontend.
# Backend giữ riêng các thao tác quản trị cần service role.
app.include_router(admin.router)

@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "OTT Arena FastAPI Backend"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
