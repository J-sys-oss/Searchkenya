@echo off
title SearchKenya Indexing Management - Demo
cd /d "%~dp0"

echo ==============================================================
echo   SearchKenya Indexing Management - starting the demo
echo   Please wait. The first run downloads a few small libraries.
echo ==============================================================
echo.

rem --- 1. find Python (the "py" launcher is the most reliable on Windows)
set "PY="
py --version >nul 2>nul && set "PY=py"
if not defined PY (
    python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [PROBLEM] Python is not installed on this computer.
    echo.
    echo  1. A download page will open now. Download Python and run the installer.
    echo  2. On the FIRST installer screen, tick "Add python.exe to PATH".
    echo  3. When it finishes, double-click this file again.
    echo.
    start "" https://www.python.org/downloads/
    pause
    exit /b 1
)

rem --- 2. make a private environment (first run only)
if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [PROBLEM] Could not create the environment. Try moving this folder to your Desktop and run again.
        pause
        exit /b 1
    )
)

rem --- 3. install the libraries (quick after the first time)
echo Installing libraries...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo [PROBLEM] Library install failed. Check that you are connected to the internet, then run again.
    pause
    exit /b 1
)

rem --- 4. open the browser a few seconds from now, then start the site
echo.
echo Starting the site. Your browser will open in a few seconds.
echo   Username: admin
echo   Password: Demo-Pass-2026!
echo.
echo KEEP THIS WINDOW OPEN while you use the site. Close it to stop.
echo.
start "" /min cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:5000"
".venv\Scripts\python.exe" demo.py

echo.
echo The demo has stopped. If you saw a red error above, copy it and send it to me.
pause
