@echo off
if exist "%~dp0server.py" (cd /d "%~dp0") else (cd /d "%~dp0..")
call venv\Scripts\activate
set OTT_TEST=1
echo === Chot thi dau vao (cham 2 bot vs bot BTC) ===
python tournament.py entry-close
echo === Cho 2 bot dau voi nhau 3 ngay ===
python tournament.py run-all
python tournament.py status
echo.
echo Xem ket qua: python client.py board TEN
pause
