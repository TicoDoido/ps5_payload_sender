@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo Windows build failed with exit code %RC%.
exit /b %RC%
