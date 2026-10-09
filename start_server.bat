@echo off
if exist "%~dp0server.py" (cd /d "%~dp0") else (cd /d "%~dp0..")
if not exist server.py (
  echo LOI: khong thay server.py trong %CD%
  pause
  exit /b 1
)
call venv\Scripts\activate
python serve.py
pause
