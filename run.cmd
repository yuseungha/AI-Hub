@echo off
cd /d "%~dp0"
if exist "dist\AIHub.exe" (
  start "" "dist\AIHub.exe"
  exit /b
)
if exist "..\dayline\.venv\Scripts\pythonw.exe" (
  start "" "..\dayline\.venv\Scripts\pythonw.exe" "app.py"
  exit /b
)
echo AIHub.exe is missing. See README.md for build instructions.
pause
