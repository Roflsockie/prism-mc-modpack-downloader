@echo off
setlocal
cd /d "%~dp0"

echo [1/5] Checking for virtual environment...
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

echo [2/5] Checking download folder...
if not exist download (
    mkdir download
    echo Created download folder.
) else (
    echo Download folder already exists.
)

echo [3/5] Activating virtual environment...
call venv\Scripts\activate

echo [4/5] Installing dependencies...
pip install -r requirements.txt

echo [5/5] Starting Modpack Downloader...
start http://localhost:5000
python app.py

pause
