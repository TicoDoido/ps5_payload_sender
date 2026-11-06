@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-android-sdk.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo Android SDK setup failed with exit code %RC%.
exit /b %RC%
