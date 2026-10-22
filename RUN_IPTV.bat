@echo off
title TVHub Server

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Consulte o README.md para instalar.
    pause
    exit /b 1
)

if not defined TVHUB_PORT set "TVHUB_PORT=8080"
set "TVHUB_OPEN_BROWSER=1"

".venv\Scripts\python.exe" app.py

pause
