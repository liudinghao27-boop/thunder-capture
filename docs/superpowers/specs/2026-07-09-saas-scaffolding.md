# 雷霆捕获系统 SaaS 脚手架改造记录

> **文档版本**：v1.0  
> **创建日期**：2026-07-09  
> **关联文档**：`2026-07-09-saas-prd.md`、`2026-07-09-saas-tech-stack.md`

---

## 1. 改造目标

为阶段 5/6 的实施补齐部署、可观测性与标准化命令脚手架，确保：

- Docker Compose 健康检查有真实端点
- 新增依赖已声明在 `pyproject.toml`
- 团队使用统一命令入口（Makefile）
- 新端点附带回归测试

---

## 2. 变更清单

### 2.1 新增文件

| 文件 | 说明 |
|------|------|
| `server/api/system.py` | 系统级端点：`/api/system/health`、`/api/system/info` |
| `tests/server/test_system.py` | 健康/信息端点回归测试 |
| `Makefile` | 常用开发/部署命令 |

### 2.2 修改文件

| 文件 | 变更 |
|------|------|
| `server/main.py` | 引入并挂载 `system.router`；可选接入 Prometheus instrumentation |
| `pyproject.toml` | `adapters` 依赖增加 `structlog`、`prometheus-fastapi-instrumentator` |

### 2.3 未改动但已确认就绪的文件

| 文件 | 状态 |
|------|------|
| `.env.example` | ✅ 已包含生产必需变量 |
| `docker-compose.yml` | ✅ 已配置 PG/Redis/Server/Celery worker，健康检查指向 `/api/system/health` |
| `Dockerfile.server` | ✅ 已存在 |
| `Dockerfile.celery` | ✅ 已存在 |
| `.github/workflows/ci.yml` | ✅ 已配置 ruff + pytest + alembic check |

---

## 3. 新增端点说明

### 3.1 `GET /api/system/health`

用途：负载均衡器 / Docker / K8s 健康探测。

响应示例：

```json
{
  "status": "healthy",
  "timestamp": "2026-07-09T06:47:54.023315+00:00",
  "version": "0.2.0",
  "environment": "development",
  "dependencies": {
    "database": {"status": "ok", "url": "sqlite:///data/test_thunder.db"},
    "redis": {"status": "skipped", "detail": "Redis not configured or unreachable"}
  }
}
```

设计要点：

- 始终返回 200，避免负载均衡器在单组件故障时误杀进程。
- 数据库 URL 已脱敏，不泄露密码。
- Redis 为可选依赖，不可用时标记为 `skipped`。

### 3.2 `GET /api/system/info`

用途：公开元数据，便于客户端版本对齐。

### 3.3 `GET /api/system/metrics`

用途：Prometheus 指标端点（当 `prometheus-fastapi-instrumentator` 安装时自动暴露）。

---

## 4. Makefile 命令

```bash
make help          # 查看所有命令
make install       # 安装生产依赖
make dev           # 安装开发依赖
make lint          # ruff 检查 + 格式检查
make format        # ruff 自动修复 + 格式化
make test          # 运行测试
make test-cov      # 运行测试并生成覆盖率报告
make migrate       # 执行数据库迁移
make migrate-check # 检查迁移是否最新
make docker-up     # 启动 Docker Compose
make docker-down   # 停止 Docker Compose
make docker-logs   # 查看 Docker 日志
make health        # 检查本地服务健康状态
```

---

## 5. 验证结果

| 检查项 | 命令 | 结果 |
|--------|------|------|
| ruff lint | `ruff check server/api/system.py server/main.py` | ✅ 通过 |
| 健康端点功能 | `pytest tests/server/test_system.py` | ✅ 4 passed |

---

## 6. 待 Phase 5/6 继续完成

| 事项 | 阶段 |
|------|------|
| 将 `logging_config.py` 迁移到 `structlog` 结构化日志 | 阶段 5 |
| 配置 Prometheus 指标与 Alertmanager 告警 | 阶段 6 |
| 添加 Celery Beat 定时调度服务到 docker-compose | 阶段 5 |
| 多租户中间件与租户隔离测试 | 阶段 6 |
| 注册/订阅/套餐限额 API 与页面 | 阶段 6 |

---

## 7. 决策记录

| 决策 | 原因 |
|------|------|
| 不一次性重写日志系统 | 避免破坏现有日志行为；结构化日志在 TDD 阶段按测试推进 |
| Prometheus 作为可选依赖 | 本地开发不需要；Docker 生产镜像会安装 |
| 健康端点始终返回 200 | 符合 K8s liveness 最佳实践；具体状态在 body 中 |

---

*本文档由 SaaS Dev Playbook Phase 4 生成。*
