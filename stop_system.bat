@echo off
chcp 65001 >nul
echo ===================================================
echo Stopping Thunder Capture FastAPI Server (Port 8000)...
echo ===================================================

:: Kill all uvicorn processes
taskkill /f /im uvicorn.exe >nul 2>&1

:: Kill processes holding port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo.
echo [OK] Server stopped successfully.
ping -n 4 127.0.0.1 >nul
