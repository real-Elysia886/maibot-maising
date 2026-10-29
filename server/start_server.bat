@echo off
chcp 65001 >nul
title AI Singing Inference Server (Port 9881)

set PYTHONNOUSERSITE=1
cd /d "%~dp0"

echo ========================================================
echo        AI Singing Inference Backend Server
echo ========================================================
echo.

set "PY_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PY_EXE=%~dp0.venv\Scripts\python.exe"
if defined SING_PYTHON set "PY_EXE=%SING_PYTHON%"

echo [Info] Using Python: %PY_EXE%
echo [Info] Starting sing_server.py (see settings.json for host and port) ...
echo.

"%PY_EXE%" -s "%~dp0sing_server.py"

pause
