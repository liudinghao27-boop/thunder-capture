.PHONY: help install dev lint format test test-cov migrate migrate-check docker-up docker-down docker-logs health

PYTHON := python
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff
ALEMBIC := $(PYTHON) -m alembic

help:
	@echo "Thunder Capture — 常用命令"
	@echo "  make install      安装生产依赖"
	@echo "  make dev          安装开发依赖"
	@echo "  make lint         运行 ruff 检查"
	@echo "  make format       运行 ruff 自动格式化"
	@echo "  make test         运行测试"
	@echo "  make test-cov     运行测试并生成覆盖率报告"
	@echo "  make migrate      执行数据库迁移到最新版本"
	@echo "  make migrate-check 检查迁移是否最新"
	@echo "  make docker-up    启动 Docker Compose 服务"
	@echo "  make docker-down  停止 Docker Compose 服务"
	@echo "  make docker-logs  查看 Docker Compose 日志"
	@echo "  make health       检查本地服务健康状态"

install:
	$(PYTHON) -m pip install -e ".[adapters]"

dev:
	$(PYTHON) -m pip install -e ".[adapters,dev]"

lint:
	$(RUFF) check server/ core/ tests/ adapters/ cli.py
	$(RUFF) format --check server/ core/ tests/ adapters/ cli.py

format:
	$(RUFF) check --fix server/ core/ tests/ adapters/ cli.py
	$(RUFF) format server/ core/ tests/ adapters/ cli.py

test:
	$(PYTEST) tests/ -q --tb=short

test-cov:
	$(PYTEST) tests/ --cov=server --cov=core --cov-report=term-missing --cov-report=html

migrate:
	$(ALEMBIC) upgrade head

migrate-check:
	$(ALEMBIC) check

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

health:
	@curl -s http://localhost:8000/api/system/live | $(PYTHON) -m json.tool
