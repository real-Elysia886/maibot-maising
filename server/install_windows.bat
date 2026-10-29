@echo off
chcp 65001 >nul
title MaiBot Singing - Windows installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0install_windows.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" echo Installation failed. See the message above.
pause
exit /b %RESULT%
