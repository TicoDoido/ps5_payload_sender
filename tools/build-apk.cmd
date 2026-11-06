@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-apk.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo APK build failed with exit code %RC%.
exit /b %RC%
