@echo off
cd /d "%~dp0"

if not exist "logs" mkdir logs

rem Local desktop default: run against SQLite so Web UI can start without Docker/PostgreSQL.
if "%THUNDER_DATABASE_URL%"=="" set THUNDER_DATABASE_URL=sqlite:///data/thunder.db
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE=.venv\Scripts\python.exe
) else (
    set PYTHON_EXE=python
)

start /b %PYTHON_EXE% -m uvicorn server.main:app --host 127.0.0.1 --port 8000 > logs\webui-server.out.log 2> logs\webui-server.err.log
ping -n 4 127.0.0.1 >nul
start http://127.0.0.1:8000/
