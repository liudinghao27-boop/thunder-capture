@echo off
setlocal
cd /d "%~dp0\..\.."

if not exist "output" mkdir output

if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE=.venv\Scripts\python.exe
) else (
    set PYTHON_EXE=python
)

set THUNDER_DATABASE_URL=sqlite:///data/thunder.db
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

%PYTHON_EXE% scripts\smoke\ui_sync_e2e.py %*
exit /b %ERRORLEVEL%
