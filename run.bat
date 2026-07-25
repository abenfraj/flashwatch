@echo off
REM Launch the overlay. Uses the local venv if present, otherwise the system
REM Python. pythonw.exe is preferred so no console window sits behind the game.
setlocal

set HERE=%~dp0

if exist "%HERE%.venv\Scripts\pythonw.exe" (
    start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%src\main.py"
    goto :eof
)

if exist "%HERE%.venv\Scripts\python.exe" (
    "%HERE%.venv\Scripts\python.exe" "%HERE%src\main.py"
    goto :eof
)

echo No virtual environment found. Create one with:
echo     py -3.11 -m venv .venv
echo     .venv\Scripts\python -m pip install -r requirements.txt
echo.
echo Falling back to the system Python...
python "%HERE%src\main.py"
