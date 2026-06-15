@echo off
cd /d "%~dp0"
start /b python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 > server.log 2>&1
ping -n 4 127.0.0.1 >nul
start http://127.0.0.1:8000/
