@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update.ps1"
set "updateExit=%errorlevel%"
pause
exit /b %updateExit%
