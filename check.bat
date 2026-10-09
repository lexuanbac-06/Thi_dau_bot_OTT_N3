@echo off
if exist "%~dp0server.py" (cd /d "%~dp0") else (cd /d "%~dp0..")
echo Thu muc dang chay: %CD%
echo --- cac file trong thu muc ---
dir /b *.py
echo --- python ---
where python
python --version
if exist venv (echo venv: CO) else (echo venv: CHUA CO, hay chay setup.bat)
call venv\Scripts\activate
python -c "import flask, waitress; print(\"flask, waitress: OK\")"
python engine.py test sample_bot.py
pause
