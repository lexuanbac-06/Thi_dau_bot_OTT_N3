@echo off
if exist "%~dp0server.py" (cd /d "%~dp0") else (cd /d "%~dp0..")
if not exist server.py (
  echo LOI: khong thay server.py trong %CD%
  pause
  exit /b 1
)
python -m venv venv
call venv\Scripts\activate
pip install flask waitress
echo Cai dat xong. Thu bot mau:
python engine.py test sample_bot.py
pause
