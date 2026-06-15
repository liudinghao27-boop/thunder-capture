@echo off
chcp 65001 >nul
title 雷霆捕获系统 — 一键安装器

echo.
echo  ⚡ 雷霆捕获系统 v0.2 安装器
echo  ────────────────────────────────
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 请先安装 Python 3.10+
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 请先安装 Docker Desktop
    echo 下载: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

echo [1/5] 安装 Python 依赖...
pip install -r requirements/base.txt -r requirements/server.txt -q

echo [2/5] 启动数据库服务 (PostgreSQL + Redis)...
docker compose up -d postgres redis

echo [3/5] 初始化数据库表...
python -c "from server.main import app; print('数据库就绪')"

echo [4/5] 创建默认管理员账户...
python -c "from server.models.user import create_default_admin; create_default_admin()"

echo [5/5] 启动服务...
start "Thunder API" cmd /c "uvicorn server.main:app --host 0.0.0.0 --port 8000"

echo.
echo  ✅ 安装完成!
echo.
echo  访问控制台: http://localhost:8000
echo  默认账号:   admin / admin123
echo  请在浏览器中登录并修改密码。
echo.
echo  配置文件:   .env  (填你的 DeepSeek API Key)
echo  行业配置:   config/industries/  (编辑你的获客关键词)
echo.
pause
