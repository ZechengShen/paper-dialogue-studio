@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\setup.ps1"
if errorlevel 1 (
  echo Setup failed. Read the message above, then retry.
  pause
  exit /b 1
)
echo Setup complete. Open the launcher to start the local website.
pause
