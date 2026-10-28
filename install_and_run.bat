@echo off
cd /d "%~dp0"
echo ========================================
echo          Virel Browser Setup
echo ========================================
echo.
python --version
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from python.org and enable Add Python to PATH.
  pause
  exit /b 1
)
echo.
echo Installing browser dependencies. This download is large because it includes a web engine.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Check your internet connection and README.md.
  pause
  exit /b 1
)
echo.
echo Starting Virel Browser...
python main.py
if errorlevel 1 pause
