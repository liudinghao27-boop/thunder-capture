# 雷霆捕获系统 SaaS 技术栈选型文档

> **文档版本**：v1.0  
> **创建日期**：2026-07-09  
> **关联文档**：`2026-07-09-saas-prd.md`、`2026-07-09-saas-uiux-design.md`  
> **决策原则**：最小变更、保留现有投入、仅引入必要新组件

---

## 1. 当前技术栈

| 层级 | 技术 | 版本/说明 |
|------|------|-----------|
| 语言 | Python | 3.10+ |
| Web 框架 | FastAPI | 异步 API、自动 OpenAPI 文档 |
| ORM | SQLAlchemy 2.x | 同步会话 + async 可选 |
| 迁移 | Alembic | 数据库版本管理 |
| 任务队列 | Celery + Redis | 后台任务、定时任务 |
| 数据库 | PostgreSQL（生产）/ SQLite（本地/测试） | 当前双模式 |
| 前端 | Vanilla JS + Tailwind CSS | 无框架，服务端渲染模板 |
| 浏览器自动化 | Playwright / MediaCrawler / Open-AutoGLM | 采集与发送 |
| 配置管理 | Pydantic Settings + YAML | 逐步迁移至 DB |
| 认证 | JWT (python-jose) + bcrypt | 当前实现 |

---

## 2. 阶段 5/6 新增需求与选型

### 2.1 后端：多租户方案

#### 候选方案对比

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **Schema-per-tenant** | 数据隔离强、可单独备份 | 连接池复杂、迁移成本高、RDS 支持有限 | ❌ 不适用 |
| **Row-level Security（RLS）** | 数据库级隔离、租户共享连接 | 需要 PostgreSQL RLS 策略、SQLAlchemy 集成复杂 | ⚠️ 可选增强 |
| **Row-level tenant_id + 应用层过滤** | 最小变更、兼容 SQLite/PG、易测试 | 依赖应用层不遗漏、隔离由代码保证 | ✅ **选中** |
| **独立数据库 per tenant** | 隔离最强 | 成本高、运维复杂 | ❌ 不适用 |

#### 决策

- **默认采用 `tenant_id` + 应用层过滤**。
- 所有模型增加 `tenant_id` 字段，查询默认带 `filter_by(tenant_id=current_tenant_id)`。
- 使用 SQLAlchemy 事件/混合属性确保不遗漏。
- SaaS 上线后评估是否对部分大客户启用 **Schema-per-tenant** 或独立 PG 实例。

### 2.2 后端：订阅与计费

| 方案 | 说明 | 结论 |
|------|------|------|
| 自研计费表 + Stripe/支付宝 | 灵活，需维护套餐/限额/发票 | ✅ **选中** |
| Stripe Billing / Lemon Squeezy | 国际 SaaS 成熟，但国内支付需额外处理 | ⚠️ 海外版可选 |
| 阿里云/腾讯云市场 | 快速上架，但抽成高、控制弱 | ⚠️ 后续拓展 |

**决策**：

- 阶段 6 先实现自研套餐/限额系统，支持按项目数、设备数、月发送量限制。
- 支付网关预留接口，国内优先支付宝/微信支付，海外预留 Stripe。
- 不引入复杂计费引擎（如 Killbill），YAGNI。

### 2.3 后端：可观测性

| 组件 | 选型 | 原因 |
|------|------|------|
| 日志 | Python `structlog` + JSON 格式 | 结构化、便于聚合 |
| 指标 | Prometheus + `prometheus-fastapi-instrumentator` | 生态成熟 |
| 告警 | Alertmanager（云端）/ 企业微信/钉钉 Webhook | 国内通知友好 |
| 链路追踪 | OpenTelemetry（可选） | 初期非必须，预留接口 |
| 健康检查 | `/health` 端点检查 DB/Redis/Celery | 必需 |

**决策**：先补齐结构化日志和健康检查；Prometheus + Alertmanager 随云端部署一起引入。

### 2.4 前端：框架选型

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 保留 Vanilla JS + Tailwind | 零迁移成本、当前团队熟悉 | 组件复用弱、状态管理手写 | ✅ **选中阶段 5** |
| 迁移到 Vite + React + shadcn/ui | 组件生态强、招聘友好 | 重写成本高、与现有风格融合难 | ⚠️ **阶段 6 后评估** |
| Next.js | SSR/SEO 强 | 对纯后台过重 | ❌ 不适用 |

**决策**：

- **阶段 5 保留 Vanilla JS + Tailwind**，仅增加响应式类与可复用 Web Components。
- **阶段 6 不强制重写前端**；若 SaaS 注册/订阅页面需要更复杂交互，可局部引入 Vue/React 微页面。
- 长期（阶段 6 之后）评估是否整体迁移到 React + shadcn/ui。

### 2.5 部署架构

| 组件 | 选型 | 说明 |
|------|------|------|
| 容器化 | Docker + Docker Compose | 阶段 6 一键启动 |
| 编排（可选） | Kubernetes | 大客户/规模化时 |
| 反向代理 | Traefik / Nginx | Traefik 与 Docker 集成更好 |
| 数据库 | PostgreSQL 16 | 生产统一 PG，弃用 SQLite 云端部署 |
| 缓存/队列 | Redis 7 | 已有 |
| 对象存储 | MinIO / 阿里云 OSS | 备份、日志、文件导出 |
| CI/CD | GitHub Actions / GitLab CI | 已有代码托管 |

**决策**：

- 阶段 6 提供 `docker-compose.yml` 作为默认部署方式。
- 提供 `k8s/` 目录作为可选生产模板。
- 云端版本不使用 SQLite，强制 PostgreSQL。

### 2.6 设备远程托管

| 方案 | 说明 | 结论 |
|------|------|------|
| 客户自有设备 + ADB over LAN/VPN | 成本低、封号风险分散 | ✅ **默认支持** |
| 云真机服务（如 STF / DeviceFarmer） | 免设备、规模化 | ✅ **阶段 6 接入** |
| 厂商定制 ROM | 长期方案 | ⚠️ 后续评估 |

**决策**：

- 保持现有 ADB/USB 模式。
- 阶段 6 引入设备接入认证（device token），支持远程 ADB over TCP 或云真机 API。

### 2.7 安全与合规工具

| 需求 | 工具/方案 |
|------|-----------|
| 依赖漏洞扫描 | `pip-audit` / Snyk |
| 密钥管理 | 环境变量 + HashiCorp Vault（云端） |
| 数据库加密 | SQLCipher（SQLite 本地）/ PG TDE（云端） |
| API 安全 | 速率限制、输入校验、JWT 短期令牌 |
| 合规 | 用户协议、隐私政策、数据导出/删除 API |

---

## 3. 最终技术栈蓝图

```
┌─────────────────────────────────────────────────────────────┐
│  Client                                                     │
│  ├── Web Admin: Vanilla JS + Tailwind CSS                   │
│  └── Mobile Web: Responsive (no separate native app yet)    │
├─────────────────────────────────────────────────────────────┤
│  API Gateway / Load Balancer                                │
│  └── Traefik / Nginx + HTTPS                                │
├─────────────────────────────────────────────────────────────┤
│  Application                                                │
│  ├── FastAPI + Pydantic                                     │
│  ├── SQLAlchemy 2.x + Alembic                               │
│  ├── Celery + Redis (tasks/scheduler)                       │
│  └── Multi-tenant middleware (tenant_id filter)             │
├─────────────────────────────────────────────────────────────┤
│  Data                                                       │
│  ├── PostgreSQL 16 (production)                             │
│  └── Redis 7 (cache/sessions/celery)                        │
├─────────────────────────────────────────────────────────────┤
│  Automation Workers                                         │
│  ├── MediaCrawler + Playwright + CDP                        │
│  └── Open-AutoGLM / ADB device workers                      │
├─────────────────────────────────────────────────────────────┤
│  Observability                                              │
│  ├── structlog JSON logs                                    │
│  ├── Prometheus metrics                                     │
│  └── Alertmanager / Webhook alerts                          │
├─────────────────────────────────────────────────────────────┤
│  Deployment                                                 │
│  ├── Docker Compose (default)                               │
│  └── Kubernetes (optional)                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 新增依赖清单

### 4.1 阶段 5 新增

| 依赖 | 用途 |
|------|------|
| `structlog` | 结构化日志 |
| `prometheus-fastapi-instrumentator` | 指标暴露 |
| `sqlcipher` / `pysqlcipher3` | SQLite 加密（本地版） |

### 4.2 阶段 6 新增

| 依赖 | 用途 |
|------|------|
| `alembic`（已存在，强化使用） | 租户相关迁移 |
| `itsdangerous` / `python-jose`（已存在） | 邮箱验证 token |
| 支付 SDK（如 `alipay-sdk-python` / `stripe`） | 订阅支付 |
| `sentry-sdk`（可选） | 错误追踪 |

---

## 5. 不引入的技术

| 技术 | 不引入原因 |
|------|-----------|
| Django / Django Ninja | 当前 FastAPI 投入大，迁移无收益 |
| Supabase / Firebase | 与现有自托管架构冲突 |
| Next.js / React（整体重写） | 阶段 5/6 成本过高，保留评估 |
| 复杂 SaaS 计费引擎（Killbill） | YAGNI，自研套餐系统足够 |
| 消息队列 Kafka | Celery + Redis 已满足 |

---

## 6. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 多租户过滤遗漏导致数据泄露 | 统一 TenantMiddleware + SQLAlchemy 查询钩子 + 隔离测试 |
| SQLite 加密密钥丢失 | 密钥派生 + 强密码策略 + 明文备份警告 |
| 支付集成复杂 | 先实现套餐限额，支付作为插件接入 |
| 可观测性工具增加运维负担 | 本地开发关闭 Prometheus，云端默认开启 |

---

## 7. 决策记录

| 决策 | 原因 | 日期 |
|------|------|------|
| 保留 FastAPI + SQLAlchemy | 已有 368 测试、成熟业务代码 | 2026-07-09 |
| 采用 row-level tenant_id | 最小变更、兼容 SQLite/PG | 2026-07-09 |
| 保留 Vanilla JS + Tailwind 阶段 5 | 避免重写、快速交付移动端 | 2026-07-09 |
| Docker Compose 作为默认部署 | 中小客户优先、运维简单 | 2026-07-09 |
| PostgreSQL 作为云端唯一数据库 | 多租户与可观测性需要 | 2026-07-09 |

---

*本文档由 SaaS Dev Playbook Phase 3 生成，作为阶段 5/6 技术实现的统一栈真相源。*
