@echo off
cd /d "%~dp0"
python main.py
if errorlevel 1 (
  echo.
  echo Virel Browser could not start. Read README.md for troubleshooting.
  pause
)
