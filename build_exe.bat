@echo off
cd /d "%~dp0"
echo This builds a Windows folder bundle, not a tiny single-file executable.
echo Qt WebEngine makes the result quite large.
echo.
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
  pause
  exit /b 1
)
python -m PyInstaller --noconfirm --clean --windowed --name VirelBrowser --icon virel.ico --add-data "assets;assets" --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets main.py
if errorlevel 1 (
  echo Build failed. Read PyInstaller output above.
  pause
  exit /b 1
)
echo.
echo Build output: dist\VirelBrowser\
pause
