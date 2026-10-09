@echo off
if exist "%~dp0server.py" (cd /d "%~dp0") else (cd /d "%~dp0..")
echo Thu muc dang chay: %CD%
call venv\Scripts\activate
echo === Chay demo, doi vai phut ===
python -u tournament.py demo 40
echo === Ket thuc, ma loi: %ERRORLEVEL% ===
python tournament.py status
pause
