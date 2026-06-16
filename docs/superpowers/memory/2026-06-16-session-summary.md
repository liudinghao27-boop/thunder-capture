# 会话记忆记录：2026-06-16

## 项目基线

- **项目路径**：`C:/Users/Administrator/Desktop/shemeihuoke`
- **当前分支**：`feat/phase1-export-compliance-new`
- **最新提交**：`1ac0c4e`（修复后续 5 项 High 风险）
- **上游审计提交**：`42b1417`
- **技术栈**：Python 3.14, FastAPI, SQLAlchemy 2.x, Pydantic 2.x, Alembic, Celery, Redis, PostgreSQL/SQLite

## 已完成的审计修复（共 30 项核心问题）

### 第一批（提交 `42b1417`）
1. Leads API 跨租户隔离
2. Stats/Dashboard funnel 跨租户隔离
3. Webhook SSRF 防护
4. Lead export HTTP 响应头拆分修复
5. 用户设置批量赋值风险修复
6. Dashboard failure distribution 未按用户过滤
7. 全局日配额 `reserved` 释放
8. `daily_send_max` 预留下发
9. Worker 字段映射修正
10. LLM 返回 `None` 保护
11. `matched_categories` 双重 JSON 编码
12. `server/services/task_stats.py` 引用不存在的列
13. Celery classify 调用修正
14. Celery send task 全局 rate limit 移除
15. Celery collect task no-op 修复
16. `generate-config-bigdata` 导入不存在模块修复
17. CLI 引用未定义函数/参数修复
18. `mark_lead_replied` 非法状态 `"sent"` 修正
19. `InMemoryRateLimiter` O(n) 修复
20. TaskQueue 复合索引
21. `system_health` 遮蔽 `db` 变量
22. 多处未使用 import 清理

### 第二批后续 High 风险（提交 `3292ef5` / `1ac0c4e`）
23. 设备重复调度：`MatrixDevice.is_available()` 对 `"running"` 返回 False
24. `core/discover.py` 与 `server/workers.py` 数据契约统一
25. `server/services/analytics.py` 全量加载改为 SQL 时间窗过滤
26. `server/services/task_stats.py` funnel 统计改为 SQL `GROUP BY` 聚合
27. `core/classify.py` 逐条入队改为批量 `INSERT ... ON CONFLICT DO NOTHING`
28. `server/api/devices.py` 异步路由中 ADB 同步 I/O 包裹 `asyncio.to_thread()`

## 验证基线

- **测试**：`python -m pytest tests/ -q --tb=short` → **199 passed, 1 warning**
- **Alembic**：`No new upgrade operations detected`
- **修改文件 ruff**：全部通过
- **全量 ruff**：约 47 errors（历史遗留）
- **全量 mypy**：约 345 errors（多数 SQLAlchemy 类型推断；mypy 2.1.0 在 Python 3.14 下偶发内部错误）

## 实测发现的问题

### 问题 1：PostgreSQL 未启动导致服务无法启动
- **现象**：运行 `start_system.bat` 后浏览器无法打开 `http://127.0.0.1:8000/`
- **根因**：`.env` 中配置了 `THUNDER_DATABASE_URL=postgresql+psycopg2://thunder:thunder123@localhost:5432/thunder`，但本地 PostgreSQL 未运行
- **日志位置**：`server.log`
- **错误**：`connection to server at "localhost", port 5432 failed: Connection refused`

### 问题 2：旧进程占用 8000 端口
- **现象**：即便切换 SQLite 后仍无法启动
- **根因**：首次启动失败的 Python/uvicorn 进程未退出，占用 `127.0.0.1:8000`
- **占用进程**：`python.exe` PID 21148
- **解决**：`taskkill //F //PID <PID>`

## 当前可用启动方式

### 方式 A：SQLite 快速实测（推荐）
```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
set THUNDER_DATABASE_URL=sqlite:///C:/Users/Administrator/Desktop/shemeihuoke/data/thunder.db
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

### 方式 B：启动 PostgreSQL 后使用原配置
```bash
docker run -d --name thunder-postgres \
  -e POSTGRES_USER=thunder \
  -e POSTGRES_PASSWORD=thunder123 \
  -e POSTGRES_DB=thunder \
  -p 5432:5432 postgres:15
```

## 剩余未完成工作

### 安全（Medium / Low）
- `scripts/smoke/reset_admin.py` 硬编码密码
- CORS 开发默认允许 `localhost:5173/3000`
- JWT 开发密钥持久化到 `data/.thunder_secret_key`
- `scripts/reset_db.py` f-string 拼接表名
- `escapeHtml()` 未转义反斜杠（前端 `server/static/index.html`）

### 逻辑（Medium / Low）
- `core/browser_orchestrator.py` 仅支持 Windows
- `core/discover.py` 与 MediaCrawler 配置文件并发冲突
- `is_send_window_open()` UTC 与本地时间比较
- ADB text input shell 注入风险
- `ProxyRotator` 保存外部列表引用
- `server/services/migrations.py` 缺失 Industry 列

### 性能（Medium / Low）
- Dashboard execution monitor N+1
- LLM 调用在 async 路由中同步阻塞
- `load_system()` 每次重新解析 YAML
- 多处列表端点无分页
- Lead export 一次性构建完整 XLSX
- `claim_token` LIKE 查询无索引
- 每条私信单独 LLM 调用
- MJPEG 每帧重新 resize

### 质量债务
- 清理剩余 ruff 47 errors
- 清理剩余 mypy 345 errors

## 环境依赖状态

- **虚拟环境**：`.venv/` 已创建，dev 依赖已安装
- **PostgreSQL**：未启动（按 `.env` 配置需要）
- **Redis**：未启动（Celery 需要）
- **ADB**：已安装

## 下一步建议

1. 先按 SQLite 方式跑通实测
2. 继续修复剩余 Medium 安全问题
3. 清理 ruff/mypy 债务
4. 如需正式部署，启动 PostgreSQL + Redis

---
**记录时间**：2026-06-16  
**记录路径**：`docs/superpowers/memory/2026-06-16-session-summary.md`
