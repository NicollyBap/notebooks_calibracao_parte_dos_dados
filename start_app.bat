@echo off
setlocal
cd /d "%~dp0"
title Tumor Fit Tool

rem 1. Find Python 3.10 or newer ("py" launcher first, then "python").
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.10 or newer is required but was not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
  echo then double-click this file again.
  pause
  exit /b 1
)

rem 2. Create the private environment on first run.
if not exist ".venv\Scripts\python.exe" (
  echo Creating the virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
  )
)

rem 3. Install dependencies if any is missing (first run only; needs internet).
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, pandas, scipy, matplotlib, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies ^(first run only, this can take a few minutes^)...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Installation failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
)

rem 4. Start the app and open the browser a few seconds later.
echo.
echo Tumor Fit Tool is running at http://127.0.0.1:8000
echo Keep this window open while you work. Close it to stop the app.
echo.
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause
