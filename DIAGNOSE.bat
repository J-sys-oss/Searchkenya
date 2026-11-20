@echo off
cd /d "%~dp0"
set "PY="
py --version >nul 2>nul && set "PY=py"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo PROBLEM: Python is not installed, or not on PATH.
  echo FIX: install Python from https://www.python.org/downloads/ and tick "Add python.exe to PATH" on the first screen.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% diagnose.py
echo.
pause
