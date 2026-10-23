@echo off
REM ============================================================
REM  start_finals.bat — Khởi động backend vòng chung kết
REM  Chỉnh sửa các biến bên dưới cho phù hợp
REM ============================================================

REM Cấu hình được đọc từ finals\.env


cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m finals.run_server
pause
