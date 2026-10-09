@echo off
if exist "%~dp0server.py" (cd /d "%~dp0") else (cd /d "%~dp0..")
call venv\Scripts\activate
set OTT_TEST=1
if exist ott.db (
  echo ott.db da ton tai. Hay xoa ott.db, bots, snaps truoc khi thu.
  pause
  exit /b 1
)
echo === Dang ky 2 thi sinh: alice va bob ===
python tournament.py add-bot alice sample_bot.py
python tournament.py add-bot bob sample_bot.py
echo === Chot thi dau vao ===
python tournament.py entry-close
echo === Ngay 1 ===
python tournament.py add-bot alice sample_bot.py
python tournament.py add-bot bob sample_bot.py
python tournament.py run-day
echo === Ngay 2 ===
python tournament.py add-bot alice sample_bot.py
python tournament.py add-bot bob sample_bot.py
python tournament.py run-day
echo === Ngay 3 - ngay cuoi ===
python tournament.py run-day
echo === KET QUA ===
python tournament.py board
python tournament.py status
echo.
echo Xong. Hay xoa ott.db, bots, snaps de don dep.
pause
