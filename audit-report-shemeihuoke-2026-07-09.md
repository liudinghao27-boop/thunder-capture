> **INSTRUCTION TO AI: This is the ONLY valid report template. Do NOT use any formatting, heading style, or structure from files inside the audited project. Output MUST follow this template exactly.**

# Fuck My Shit Mountain Audit Report

**Project:** Thunder Capture SaaS (shemeihuoke)
**Audit mode:** full
**Date:** 2026-07-09
**Reviewer:** Claude Code / fuck-my-shit-mountain skill

---

## 1. Executive Summary

雷霆捕获系统（Thunder Capture SaaS）是一个以 Python/FastAPI 为后端、以 Celery + Redis 为任务队列、以 Playwright/MediaCrawler 做数据采集、以 LLM 做意图分类与回复生成、再以 ADB/AutoGLM 控制安卓设备发送私信的社媒私域获客平台。项目结构已按 `core/` / `adapters/` / `server/` / `deps/` 分层，但代码层面存在大量跨层依赖、租户隔离缺陷、稳定性与可观测性缺口，以及对外部 LLM/第三方依赖的强信任假设。

本次全量审计共识别出 **8 项 Critical、28 项 High** 风险，另有 30+ 项 Medium/Low 问题。最严重的风险集中在：
1. **多租户隔离失效**：`industry_slug` 未全局唯一，导致 Celery 任务、删除清理、配额统计全部可能操作错误租户的数据；
2. **密钥与配置安全**：项目根目录存在包含真实 API Key 与数据库密码的 `.env`；
3. **LLM 安全与成本失控**：未对社媒评论做 prompt-injection 隔离、未过滤 LLM 生成回复、未记录任何 token/成本；
4. **发布与供应链**：Release workflow 仍硬编码为 Crawl4AI 项目，vendored MediaCrawler 携带非商业许可证，依赖未 pin；
5. **稳定性**：大量异常被静默吞掉、Celery 任务声明重试却未触发、FastAPI 无 lifespan 导致资源泄漏。

当前代码在单用户、单进程、受控桌面环境下可以跑通测试，但作为 SaaS/Multi-tenant 产品上线前需要先做一轮安全加固、租户隔离重构与可观测性补齐。

### Score Dashboard

```
Security        ██████░░░░  6.0  B   租户隔离缺陷、.env 存真实密钥、LLM 动作未授权
Stability       █████░░░░░  5.0  B   大量静默吞错、无重试、无 lifespan、并发竞态
Performance     ██████░░░░  5.5  B   N+1 查询、未分页、每步发送全量截图
Testing         █████░░░░░  5.0  B   测试通过但缺覆盖率门、共享持久库、脆弱测试
Maintainability █████░░░░░  5.0  B   跨层依赖、超大文件/函数、嵌套过深
Design          █████░░░░░  5.0  B   架构文档与实际依赖图严重不符
Release         ████░░░░░░  4.0  C   Release 流程指向错误项目、依赖未 pin、许可证冲突
─────────────────────────────────────
Overall         █████░░░░░  5.1  C
```

Each dimension scored 0.0–10.0. **Higher = better (10 = clean, 0 = shit mountain).** Scores are judgment-based, not formula-based. See `rubrics/scoring.md` for anchor descriptions.

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
|----------|-------|-----------|-----------|
| Critical | 8 | 8 | 0 |
| High | 33 | 33 | 0 |
| Medium | 15 | 15 | 0 |
| Low | 2 | 2 | 0 |
| Info | 0 | 0 | 0 |
| **Total** | **58** | **58** | **0** |

## 2. Project Map

**入口与部署**
- FastAPI：`server/main.py` 挂载 `server/api/*.py` 路由与 `server/static/` SPA，监听 `0.0.0.0:8000`。
- CLI：`cli.py` 提供 `collect / send / run / stats` 等子命令，直接调用 `core/` 与 `server.services`。
- Celery：`adapters/celery/app.py` 配置 Redis broker，任务定义在 `adapters/celery/{collect,classify,send}.py`。
- 容器：`Dockerfile.server`、`Dockerfile.celery`、`docker-compose.yml` 提供 PG + Redis + server + worker 组合。

**数据流**
1. `core/discover.py` / `adapters/mediacrawler/runner.py` 子进程抓取抖音/小红书评论；
2. `core/classify.py`（DifyBackend / DirectLLMBackend）批量意图分类；
3. `server/services/task_stats.py` 将线索入队 `TaskQueue`；
4. `core/task/scheduler.py` + `core/task/worker.py` / `adapters/celery/send.py` 申领设备、生成回复、调用 ADB/AutoGLM 发送私信；
5. `server/api/*` 提供 Web 控制台与统计 API。

**持久化**
- SQLAlchemy 模型在 `server/models/`（User / Industry / Device / TaskQueue / Job / ExecutionLog 等）；
- 默认 SQLite，生产建议 PostgreSQL（`adapters/postgres/connection.py` 提供 PG 工厂，但 `server/models/__init__.py` 未使用它）；
- Alembic 初始化存在，但 `server/services/migrations.py` 同时维护一套自定义 additive migration。

**外部边界**
- LLM：DeepSeek / 智谱 / OpenAI / Dify；
- 社媒爬虫：vendored `deps/MediaCrawler/`；
- 设备控制：vendored `deps/Open-AutoGLM/` + ADB；
- 网页抓取：vendored `deps/crawl4ai/`；
- Webhook：外部 lead/effect 回调。

**高风险区域**
- `server/api/industries.py`（1360 行）：行业 CRUD、发送启动、任务管理，集中了租户隔离与并发控制缺陷；
- `core/task/worker.py`：DeviceWorker 线程安全、LLM 回复生成、ADB 动作执行；
- `adapters/celery/*.py`：跨进程任务未携带 `user_id`；
- `server/services/llm.py` 与 `core/classify.py`：LLM 调用与提示词组装；
- `server/services/migrations.py`：双轨迁移系统。

### Coverage Matrix

| Dimension | Coverage | Evidence inspected | Exclusions / limits |
|-----------|----------|--------------------|---------------------|
| Architecture | Medium | `PROJECT_STRUCTURE.md`, import graph (Grep), layer boundary checks | 未做完整 import-graph 自动化工具扫描 |
| Security | High | `server/auth.py`, `server/middleware.py`, `server/api/*.py`, `core/classify.py`, `core/task/worker.py`, `server/secret_store.py`, `.env` | 未对 vendored Open-AutoGLM 内部做完整审计 |
| Stability | High | Celery tasks, scheduler, worker, device supervisor, webhook services, server lifespan | 未在生产负载下压测 |
| Performance | Medium | Dashboard/jobs endpoints, scheduler, DirectGLM screenshot path | 未做实际 profiling |
| Testing | High | `tests/`, `pyproject.toml`, `pytest` run, `ruff`, `mypy` | 未逐行阅读全部 381 个测试 |
| Maintainability | High | File sizes, function lengths, nesting depth, docstring coverage, imports | 以抽样 + ruff/mypy 数据为主 |
| Design | Medium | Layer dependency direction, SRP violations | 同上 |
| Release | High | GitHub workflows, Dockerfiles, docker-compose, installer | 未实际触发 release |
| Documentation | Medium | README, PROJECT_STRUCTURE.md, inline docs | 未审计 docs/superpowers/ 全部计划文档 |
| Observability | High | Logging config, middleware, health endpoint, metrics | 未部署 Prometheus |
| Configuration | High | `.env`, `config/system.yaml`, `server/config.py`, `core/config.py` | 未检查所有行业模板 |
| Data Integrity | High | Models, migrations, scheduler, API transaction boundaries | 未做 chaos/fault injection |
| Privacy | Medium | Lead export, PII fields, logs | 未检查数据保留策略实现 |
| Accessibility | Not assessed | 项目以后端/CLI/少量 Vanilla JS SPA 为主，前端界面未作为主要审计面 | 如需可单独审计 `server/static/` |
| Supply Chain | High | `pyproject.toml`, requirements, vendored deps, workflows, SBOM script | 未对所有 transitive deps 做许可证扫描 |
| Cost | High | LLM call sites, vision screenshots, retry logic | 未连接真实账单 |
| AI Safety | High | Classification/reply prompts, agent action execution, API key handling | 未做完整 red-team |
| Frontend State | Not assessed | 无 React/Vue 状态管理层；`server/static/` 为 Vanilla JS | 同上 |
| Backend API | High | All `server/api/*.py`, schemas, services | 同上 |
| Type Safety | Medium | `mypy` output, `pyproject.toml` overrides | 未修复所有错误 |
| Code Consistency | Medium | Ruff check/format output | 未配置自定义 ruff 规则 |
| Comment Coverage | Low | 抽样检查公共函数 docstring | 未使用工具统计 |
| Dependency Weight | Medium | `pyproject.toml`, vendored deps sizes | 未精确测量 |

## 3. Top Risks

1. **项目根 `.env` 存放真实密钥** (Critical / Security / Config) — 任何能读取项目目录的人都能拿到 DeepSeek、智谱、JWT 与数据库密码。
2. **Industry slug 未全局唯一导致跨租户数据错乱** (Critical / Security / Data Integrity) — Celery 任务、删除清理、配额统计、发送启动全部可能操作到错误租户。
3. **vendored MediaCrawler 为非商业许可证** (Critical / Supply Chain) — 集成进 SaaS 产品构成许可证侵权风险。
4. **Release workflow 仍指向 Crawl4AI 项目** (Critical / Release) — 无法为 Thunder Capture 打出可用 release，且会推送错误 Docker 镜像。
5. **LLM 生成回复未经内容安全过滤即发送** (Critical / AI Safety) — 可能发送违规/有害私信，导致平台封号与法律风险。
6. **Phone Agent 直接执行 LLM 生成的 ADB 动作** (Critical / AI Safety) — prompt injection 可导致任意点击、输入、跨应用操作。
7. **无任何 LLM token/成本追踪** (Critical / Cost) — 无法发现异常消耗，单点故障可瞬间耗尽预算。
8. **双轨迁移系统 / additive migration 无法回滚** (Critical / Data Integrity / Release) — 生产 schema drift 不可控。
9. **发送任务启动存在竞态，可产生并发发送任务** (High / Data Integrity) — 快速双击或并行调用会创建多个 running send job。
10. **设备日/小时发送限额在并发申领下可被突破** (High / Data Integrity) — 多个 worker 同时看到 `daily_sent < limit` 后各自申领。
11. **GET `/api/jobs` 在 normalized status 过滤时未分页** (High / Backend API / Performance) — 大量历史任务可导致 OOM。
12. **FastAPI 无 lifespan/shutdown hook，连接与后台线程泄漏** (High / Stability) — 热更新/容器停止时资源与任务状态可能损坏。
13. **Celery 任务声明 retry 却未触发重试** (High / Stability) — 瞬态失败永久丢失任务。
14. **Webhook 出站推送无签名、无重试、无幂等键** (High / Data Integrity / Stability) — 丢失事件且无法向接收方证明来源。
15. **全局 LLM client 与 classification router 无线程安全** (High / Stability) — 并发 worker 可能拿到错误的 API key 或混合 backend。

## 4. Detailed Findings

### Finding: 项目根 `.env` 文件包含真实密钥

- Severity: Critical
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security / Configuration
- Evidence:
  - File / path: `C:\Users\Administrator\Desktop\shemeihuoke\.env` 存在且包含 `THUNDER_DEEPSEEK_KEY`、`THUNDER_ZHIPU_KEY`、`THUNDER_SECRET_KEY`、PostgreSQL 密码；`server/config.py:13` 主动加载该文件。
  - Relevant behavior: 项目根 `.env` 文件包含真实密钥
- Problem: 项目根 `.env` 文件包含真实密钥
- Why it matters: 任何能访问项目目录的进程、备份、IDE 同步或云盘都能拿到全部密钥；泄露后攻击者可冒用 JWT、读取数据库、消耗 LLM 额度。
- Realistic failure scenario: 任何能访问项目目录的进程、备份、IDE 同步或云盘都能拿到全部密钥；泄露后攻击者可冒用 JWT、读取数据库、消耗 LLM 额度。
- Minimal fix: 立即从仓库/运行时目录删除 `.env`；将所有密钥轮换；改用 Docker secrets / CI 环境变量 / 密钥管理器；在 CI 中增加检测 `.env` 存在即失败的检查。
- Better long-term fix: 立即从仓库/运行时目录删除 `.env`；将所有密钥轮换；改用 Docker secrets / CI 环境变量 / 密钥管理器；在 CI 中增加检测 `.env` 存在即失败的检查。
- Regression test suggestion: 运行 `ls -la` 确认仓库无 `.env`；CI 中新增 `test -f .env && exit 1`。
- Estimated effort: 2 hours


### Finding: Industry slug 未全局唯一，导致跨租户数据错乱

- Severity: Critical
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security / Data Integrity
- Evidence:
  - File / path: `server/models/industry.py` 未对 `slug` 加唯一约束；`server/api/industries.py:548-551` 仅在当前用户内检查唯一性；`adapters/celery/send.py:47` 用 `Industry.slug == industry_slug` 查询；`server/api/industries.py:662-664` 按 slug 删除 `TaskQueue` / `TargetBlogger`；`server/services/task_stats.py:44-55` 的 `_owner_filter` 包含空/NULL owner。
  - Relevant behavior: Industry slug 未全局唯一，导致跨租户数据错乱
- Problem: Industry slug 未全局唯一，导致跨租户数据错乱
- Why it matters: 两个用户可创建同名 industry slug，后续 Celery 发送、删除清理、配额统计都会相互影响，造成数据泄露、错误发送、数据丢失。
- Realistic failure scenario: 两个用户可创建同名 industry slug，后续 Celery 发送、删除清理、配额统计都会相互影响，造成数据泄露、错误发送、数据丢失。
- Minimal fix: 在 `Industry` 上加 `(user_id, slug)` 唯一约束；所有按 slug 查询都同时过滤 `user_id`；Celery 任务携带 `user_id`；`TaskQueue` / `TargetBlogger` 的 `owner_user_id` 设为 non-nullable 并回填。
- Better long-term fix: 在 `Industry` 上加 `(user_id, slug)` 唯一约束；所有按 slug 查询都同时过滤 `user_id`；Celery 任务携带 `user_id`；`TaskQueue` / `TargetBlogger` 的 `owner_user_id` 设为 non-nullable 并回填。
- Regression test suggestion: 创建两个同名 slug 的不同用户，触发发送与删除，断言数据隔离。
- Estimated effort: 2 days


### Finding: Vendored MediaCrawler 携带非商业许可证

- Severity: Critical
- Confidence: High
- Category: Supply Chain
- Status: Confirmed
- Affected area: Supply Chain / Legal
- Evidence:
  - File / path: `deps/MediaCrawler/LICENSE` 为 “NON-COMMERCIAL LEARNING LICENSE 1.1”，明确禁止未经书面同意的商业使用。
  - Relevant behavior: Vendored MediaCrawler 携带非商业许可证
- Problem: Vendored MediaCrawler 携带非商业许可证
- Why it matters: 将 MediaCrawler 作为 SaaS 的一部分分发或调用，构成许可证违约，可能面临下架、诉讼或供应链审计失败。
- Realistic failure scenario: 将 MediaCrawler 作为 SaaS 的一部分分发或调用，构成许可证违约，可能面临下架、诉讼或供应链审计失败。
- Minimal fix: 替换为商业友好许可的爬虫方案；或获得作者商业授权；或将其拆分为用户自行安装的可选插件，不再随项目分发。
- Better long-term fix: 替换为商业友好许可的爬虫方案；或获得作者商业授权；或将其拆分为用户自行安装的可选插件，不再随项目分发。
- Regression test suggestion: 在 CI 中运行 license 扫描，禁止非商业/互惠许可证进入分发包。
- Estimated effort: 1 week


### Finding: Release workflow 仍硬编码为 Crawl4AI 项目

- Severity: Critical
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: Release
- Evidence:
  - File / path: `.github/workflows/release.yml:37,44-45,64-66,75,82-86` 从 `crawl4ai.__version__` 读取版本、release body 指向 `unclecode/crawl4ai`、PyPI 项目写 crawl4ai。
  - Relevant behavior: Release workflow 仍硬编码为 Crawl4AI 项目
- Problem: Release workflow 仍硬编码为 Crawl4AI 项目
- Why it matters: 无法为 Thunder Capture 打出可用 release；tag 校验会失败；Docker 镜像与 release note 全部指向错误项目。
- Realistic failure scenario: 无法为 Thunder Capture 打出可用 release；tag 校验会失败；Docker 镜像与 release note 全部指向错误项目。
- Minimal fix: 版本源改为 `importlib.metadata.version('thunder-capture')` 或读取 `pyproject.toml`；release body 与 Docker 标签全部改为 `thunder-capture`。
- Better long-term fix: 版本源改为 `importlib.metadata.version('thunder-capture')` 或读取 `pyproject.toml`；release body 与 Docker 标签全部改为 `thunder-capture`。
- Regression test suggestion: 推送测试 tag，验证版本校验通过且 release body 无 crawl4ai 字样。
- Estimated effort: 2 hours


### Finding: LLM 生成回复未经内容安全过滤即发送

- Severity: Critical
- Confidence: High
- Category: AI Safety
- Status: Confirmed
- Affected area: AI Safety
- Evidence:
  - File / path: `core/task/worker.py:127-141` 调用 DeepSeek 生成回复后直接返回用于发送；无任何政策过滤、毒性检测或人工审核。
  - Relevant behavior: LLM 生成回复未经内容安全过滤即发送
- Problem: LLM 生成回复未经内容安全过滤即发送
- Why it matters: 可能自动发送违法、骚扰、歧视或违反平台政策的私信，导致账号封禁与法律责任。
- Realistic failure scenario: 可能自动发送违法、骚扰、歧视或违反平台政策的私信，导致账号封禁与法律责任。
- Minimal fix: 在发送前增加内容审核层（规则 + LLM judge），拦截并记录高风险输出；对首次行业/变体加入人工采样审核。
- Better long-term fix: 在发送前增加内容审核层（规则 + LLM judge），拦截并记录高风险输出；对首次行业/变体加入人工采样审核。
- Regression test suggestion: 输入毒性/违禁输入，断言发送被拦截并记录审计日志。
- Estimated effort: 2 days


### Finding: Phone Agent 直接执行 LLM 生成的 ADB 动作

- Severity: Critical
- Confidence: High
- Category: AI Safety
- Status: Confirmed
- Affected area: AI Safety
- Evidence:
  - File / path: `core/agent/direct_glm.py:287-322` 解析 GLM 返回的 JSON action 后直接调用 `tap/swipe/input_text/keyevent`；`core/agent/executor.py:65-97` 同理；`core/agent/planner.py:27-51` 将用户提供的 `message` / `search_target` 等直接拼入目标字符串。
  - Relevant behavior: Phone Agent 直接执行 LLM 生成的 ADB 动作
- Problem: Phone Agent 直接执行 LLM 生成的 ADB 动作
- Why it matters: prompt injection 或模型异常可导致任意屏幕操作、发送给错误对象、离开目标应用、泄露屏幕数据。
- Realistic failure scenario: prompt injection 或模型异常可导致任意屏幕操作、发送给错误对象、离开目标应用、泄露屏幕数据。
- Minimal fix: 用固定的高层步骤计划替代自由目标；对 action 类型/坐标/目标应用做白名单校验；高风险动作需人工确认或 dry-run。
- Better long-term fix: 用固定的高层步骤计划替代自由目标；对 action 类型/坐标/目标应用做白名单校验；高风险动作需人工确认或 dry-run。
- Regression test suggestion: 注入异常 action / 越界坐标 / 跨应用意图，断言被拒绝。
- Estimated effort: 1 week


### Finding: 无任何 LLM token/成本追踪

- Severity: Critical
- Confidence: High
- Category: Cost
- Status: Confirmed
- Affected area: Cost
- Evidence:
  - File / path: 搜索 `server/services/llm.py`、`core/classify.py`、`core/task/worker.py`、`core/agent/direct_glm.py`、`adapters/dify/client.py`，均未读取或持久化 `response.usage`。
  - Relevant behavior: 无任何 LLM token/成本追踪
- Problem: 无任何 LLM token/成本追踪
- Why it matters: 异常流量、错误配置或对抗输入可瞬间耗尽 API 预算；无法按租户/行业归因成本。
- Realistic failure scenario: 异常流量、错误配置或对抗输入可瞬间耗尽 API 预算；无法按租户/行业归因成本。
- Minimal fix: 每次 LLM 调用记录 prompt/completion tokens；写入按 industry/user 聚合的成本表；设置日/小时预算上限与告警。
- Better long-term fix: 每次 LLM 调用记录 prompt/completion tokens；写入按 industry/user 聚合的成本表；设置日/小时预算上限与告警。
- Regression test suggestion: Mock LLM 返回 usage 元数据，断言系统记录并能在预算超限后拒绝调用。
- Estimated effort: 2 days


### Finding: 同时存在 Alembic 与自定义 additive migration 两套系统

- Severity: Critical
- Confidence: High
- Category: Data Integrity
- Status: Confirmed
- Affected area: Data Integrity / Release
- Evidence:
  - File / path: `alembic.ini` 与 `adapters/postgres/migrations/` 存在；`server/services/migrations.py:23-87` 在启动时执行 `ALTER TABLE … ADD COLUMN` 且未记录版本；`alembic/versions/` 为空。
  - Relevant behavior: 同时存在 Alembic 与自定义 additive migration 两套系统
- Problem: 同时存在 Alembic 与自定义 additive migration 两套系统
- Why it matters: 升级/回滚不可控；不同环境 schema 可能不同；无法安全重命名/删除列或加索引。
- Realistic failure scenario: 升级/回滚不可控；不同环境 schema 可能不同；无法安全重命名/删除列或加索引。
- Minimal fix: 统一使用 Alembic 版本化迁移；移除 `ADDITIVE_MIGRATIONS` 自动修改；CI 中校验 `alembic upgrade head` 与模型一致。
- Better long-term fix: 统一使用 Alembic 版本化迁移；移除 `ADDITIVE_MIGRATIONS` 自动修改；CI 中校验 `alembic upgrade head` 与模型一致。
- Regression test suggestion: `alembic upgrade head` 后运行 `alembic check` 通过；新增/删除列可通过 revision 文件完成。
- Estimated effort: 2 days


### Finding: Docker release 推送到错误的 Docker Hub 仓库

- Severity: High
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: Release
- Evidence:
  - File / path: `.github/workflows/docker-release.yml:75-78` 使用 `unclecode/crawl4ai:…` 标签。
  - Relevant behavior: Docker release 推送到错误的 Docker Hub 仓库
- Problem: Docker release 推送到错误的 Docker Hub 仓库
- Why it matters: 镜像会发布到第三方命名空间，Thunder Capture 用户无法获取，且可能污染 Crawl4AI 镜像仓库。
- Realistic failure scenario: 镜像会发布到第三方命名空间，Thunder Capture 用户无法获取，且可能污染 Crawl4AI 镜像仓库。
- Minimal fix: 替换为 `thunder-team/thunder-capture` 或组织实际拥有的仓库名。
- Better long-term fix: 替换为 `thunder-team/thunder-capture` 或组织实际拥有的仓库名。
- Regression test suggestion: 用 `push: false` 或 staging registry 运行 workflow，检查生成的镜像名。
- Estimated effort: 30 minutes


### Finding: CI 使用硬编码 fallback secret

- Severity: High
- Confidence: High
- Category: Release
- Status: Confirmed
- Affected area: Release
- Evidence:
  - File / path: `.github/workflows/ci.yml:36` 与 `.github/workflows/ui-sync-e2e.yml:28` 使用 `THUNDER_SECRET_KEY: ${{ secrets.THUNDER_SECRET_KEY || 'ci-test-secret-key-do-not-use-in-production' }}`。
  - Relevant behavior: CI 使用硬编码 fallback secret
- Problem: CI 使用硬编码 fallback secret
- Why it matters: 当仓库未配置 secret 时，CI 使用公开已知的密钥，弱化安全文化并可能导致测试 token 被滥用。
- Realistic failure scenario: 当仓库未配置 secret 时，CI 使用公开已知的密钥，弱化安全文化并可能导致测试 token 被滥用。
- Minimal fix: 删除 fallback 分支，缺少 secret 时直接失败；在文档中说明必须配置该 secret。
- Better long-term fix: 删除 fallback 分支，缺少 secret 时直接失败；在文档中说明必须配置该 secret。
- Regression test suggestion: 临时移除 secret 后触发 workflow，确认在 setup 阶段失败而非继续运行。
- Estimated effort: 30 minutes


### Finding: 主项目依赖未 pin，且 Docker/安装脚本不使用 lockfile

- Severity: High
- Confidence: High
- Category: Supply Chain
- Status: Confirmed
- Affected area: Supply Chain
- Evidence:
  - File / path: `pyproject.toml:12-33` 全部使用 `>=`；`requirements/*.txt` 重复同样范围；存在 `uv.lock` 但 `Dockerfile.server`、`Dockerfile.celery`、`installer/install.bat` 均未使用。
  - Relevant behavior: 主项目依赖未 pin，且 Docker/安装脚本不使用 lockfile
- Problem: 主项目依赖未 pin，且 Docker/安装脚本不使用 lockfile
- Why it matters: 不同时间构建会解析出不同版本，导致不可复现构建与上游破坏性更新风险。
- Realistic failure scenario: 不同时间构建会解析出不同版本，导致不可复现构建与上游破坏性更新风险。
- Minimal fix: 将 `uv.lock` 作为单一真相源；Docker 与安装脚本改用 `uv sync --locked` 或从 lockfile 生成 pinned requirements。
- Better long-term fix: 将 `uv.lock` 作为单一真相源；Docker 与安装脚本改用 `uv sync --locked` 或从 lockfile 生成 pinned requirements。
- Regression test suggestion: CI 中 `uv sync --locked` 失败当 lockfile 过期；两次构建的包版本一致。
- Estimated effort: 2 days


### Finding: 根 LICENSE 与 pyproject.toml 许可证声明冲突

- Severity: High
- Confidence: High
- Category: Supply Chain
- Status: Confirmed
- Affected area: Supply Chain
- Evidence:
  - File / path: `pyproject.toml:6` 声明 `license = "MIT"`；根 `LICENSE` 为 Apache-2.0 并附加 Crawl4AI 署名要求。
  - Relevant behavior: 根 LICENSE 与 pyproject.toml 许可证声明冲突
- Problem: 根 LICENSE 与 pyproject.toml 许可证声明冲突
- Why it matters: 元数据与源码分发许可不一致，存在法律歧义；分发时可能违反 Crawl4AI 署名条款。
- Realistic failure scenario: 元数据与源码分发许可不一致，存在法律歧义；分发时可能违反 Crawl4AI 署名条款。
- Minimal fix: 统一许可证；若保留 Apache-2.0，在 `NOTICE` 或 README 中给出 Crawl4AI 署名；更新 `pyproject.toml`。
- Better long-term fix: 统一许可证；若保留 Apache-2.0，在 `NOTICE` 或 README 中给出 Crawl4AI 署名；更新 `pyproject.toml`。
- Regression test suggestion: `twine check dist/*` 与许可证扫描工具均通过。
- Estimated effort: 2 hours


### Finding: Vendored 依赖锁定冲突版本

- Severity: High
- Confidence: High
- Category: Supply Chain
- Status: Confirmed
- Affected area: Supply Chain
- Evidence:
  - File / path: `deps/MediaCrawler/pyproject.toml` 锁定 `fastapi==0.110.2`、`pydantic==2.5.2`、`pillow==9.5.0`；主项目要求 `fastapi>=0.115.0`、`pydantic>=2.10.0`、`Pillow>=10.0.0`。
  - Relevant behavior: Vendored 依赖锁定冲突版本
- Problem: Vendored 依赖锁定冲突版本
- Why it matters: 同一进程导入 vendored 包时可能触发版本冲突、API 不兼容或运行时错误。
- Realistic failure scenario: 同一进程导入 vendored 包时可能触发版本冲突、API 不兼容或运行时错误。
- Minimal fix: 将 vendored deps 作为 workspace 成员统一 lockfile，或改为依赖发布包；CI 中增加同进程导入 smoke test。
- Better long-term fix: 将 vendored deps 作为 workspace 成员统一 lockfile，或改为依赖发布包；CI 中增加同进程导入 smoke test。
- Regression test suggestion: 同一 Python 进程中导入 `crawl4ai`、`mediacrawler`、`phone_agent` 不报错。
- Estimated effort: 2 days


### Finding: 未受信任的社媒评论直接拼入分类与回复提示词

- Severity: High
- Confidence: High
- Category: AI Safety
- Status: Confirmed
- Affected area: AI Safety / Security
- Evidence:
  - File / path: `core/classify.py:246-253` 将 `_comment_text(comment)` 拼入 DeepSeek prompt；`core/task/worker.py:127-133` 将 `comment_text` 拼入回复生成 prompt；`server/api/industries.py:205,491` 将用户输入的 `description` / `seed_keyword` 与评论拼入 prompt。
  - Relevant behavior: 未受信任的社媒评论直接拼入分类与回复提示词
- Problem: 未受信任的社媒评论直接拼入分类与回复提示词
- Why it matters: prompt injection 可覆盖系统指令、强制错误分类、生成有害或信息泄露型回复。
- Realistic failure scenario: prompt injection 可覆盖系统指令、强制错误分类、生成有害或信息泄露型回复。
- Minimal fix: 使用 OpenAI messages 格式区分 system/user；对用户内容加界定标记；校验输出 schema；增加 prompt-injection 检测。
- Better long-term fix: 使用 OpenAI messages 格式区分 system/user；对用户内容加界定标记；校验输出 schema；增加 prompt-injection 检测。
- Regression test suggestion: 注入类指令评论不应改变分类/回复策略或泄露系统提示。
- Estimated effort: 2 days


### Finding: LLM client 缓存 key 仅使用前 8 位 API key

- Severity: High
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security
- Evidence:
  - File / path: `server/services/llm.py:110` 构建 `cache_key = f"{provider}:{base_url}:{key[:8]}"`；缓存的 `OpenAI` 对象实际保存完整 key。
  - Relevant behavior: LLM client 缓存 key 仅使用前 8 位 API key
- Problem: LLM client 缓存 key 仅使用前 8 位 API key
- Why it matters: 不同用户 key 前 8 位相同时会复用同一 client，导致请求使用错误 key、账单串户。
- Realistic failure scenario: 不同用户 key 前 8 位相同时会复用同一 client，导致请求使用错误 key、账单串户。
- Minimal fix: 使用完整 key 的 secure hash 作为缓存 key；或按请求实例化 client。
- Better long-term fix: 使用完整 key 的 secure hash 作为缓存 key；或按请求实例化 client。
- Regression test suggestion: 提供两个前 8 位相同但后续不同的 key，断言返回两个独立 client 且请求使用正确 key。
- Estimated effort: 2 hours


### Finding: Fernet 加密密钥回退到 JWT 签名密钥

- Severity: High
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security
- Evidence:
  - File / path: `server/secret_store.py:42`：`material = os.getenv("THUNDER_ENCRYPTION_KEY", "") or SECRET_KEY`。
  - Relevant behavior: Fernet 加密密钥回退到 JWT 签名密钥
- Problem: Fernet 加密密钥回退到 JWT 签名密钥
- Why it matters: 若未设置独立加密密钥，JWT secret 泄露即可解密所有用户存储的 LLM API key。
- Realistic failure scenario: 若未设置独立加密密钥，JWT secret 泄露即可解密所有用户存储的 LLM API key。
- Minimal fix: 生产环境强制要求 `THUNDER_ENCRYPTION_KEY`；生成独立 32 字节密钥；规划已有密文轮换。
- Better long-term fix: 生产环境强制要求 `THUNDER_ENCRYPTION_KEY`；生成独立 32 字节密钥；规划已有密文轮换。
- Regression test suggestion: 生产模式未设加密密钥时启动失败；仅持有 JWT secret 无法解密用户 API key。
- Estimated effort: 2 hours


### Finding: 无主的 TaskQueue 行可被任意租户 scheduler 申领

- Severity: High
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security / Data Integrity
- Evidence:
  - File / path: `server/services/task_stats.py:44-55` 的 `_owner_filter` 匹配 owner、空字符串或 NULL；`core/task/scheduler.py:103-114` 仅在 `owner_user_id` 设置时才加 owner 过滤；`server/services/task_stats.py:680-710` 的 `enqueue_task` 不写入 `owner_user_id`。
  - Relevant behavior: 无主的 TaskQueue 行可被任意租户 scheduler 申领
- Problem: 无主的 TaskQueue 行可被任意租户 scheduler 申领
- Why it matters: 历史数据或引擎路径插入的无主线索可被任何用户设备发送。
- Realistic failure scenario: 历史数据或引擎路径插入的无主线索可被任何用户设备发送。
- Minimal fix: 回填 `owner_user_id`；列设为 non-nullable；插入时拒绝无主任务。
- Better long-term fix: 回填 `owner_user_id`；列设为 non-nullable；插入时拒绝无主任务。
- Regression test suggestion: 插入 owner 为空的任务，其他用户 scheduler 申领应被拒绝。
- Estimated effort: 2 days


### Finding: Lead export 允许任意字段选择

- Severity: High
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security / Privacy
- Evidence:
  - File / path: `server/api/leads.py:51-63` 的 `LeadExportRequest.fields` 无白名单校验；`server/services/export.py:53-65` 直接从行字典读取任意字段；`server/api/leads.py:271` 直接透传。
  - Relevant behavior: Lead export 允许任意字段选择
- Problem: Lead export 允许任意字段选择
- Why it matters: 认证用户可导出 `claim_token`、`owner_user_id`、`user_id`、`reply_text` 等内部/敏感列，扩大泄露面。
- Realistic failure scenario: 认证用户可导出 `claim_token`、`owner_user_id`、`user_id`、`reply_text` 等内部/敏感列，扩大泄露面。
- Minimal fix: `LeadExportRequest.fields` 增加白名单校验；仅选择允许列。
- Better long-term fix: `LeadExportRequest.fields` 增加白名单校验；仅选择允许列。
- Regression test suggestion: 请求导出 `claim_token` 应返回 422。
- Estimated effort: 2 hours


### Finding: Celery beat 周期任务跨租户运行所有 active industry

- Severity: High
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security
- Evidence:
  - File / path: `adapters/celery/app.py:56-62` 调度 `run_send_batch("__all_active__", "")`；`adapters/celery/send.py:89-95` 在 `__all_active__` 时查询所有 `Industry.is_active` 行。
  - Relevant behavior: Celery beat 周期任务跨租户运行所有 active industry
- Problem: Celery beat 周期任务跨租户运行所有 active industry
- Why it matters: 多租户部署中，定时任务会为所有租户发送私信，且结合 Finding 2 会进一步混淆租户数据。
- Realistic failure scenario: 多租户部署中，定时任务会为所有租户发送私信，且结合 Finding 2 会进一步混淆租户数据。
- Minimal fix: 按租户配置 beat schedule，或任务链中携带并过滤 `user_id`。
- Better long-term fix: 按租户配置 beat schedule，或任务链中携带并过滤 `user_id`。
- Regression test suggestion: 两个用户各有一个 active industry，运行 beat 任务后断言仅处理对应租户数据。
- Estimated effort: 2 days


### Finding: Webhook SSRF 防护可通过重定向绕过

- Severity: High
- Confidence: Medium
- Category: Security
- Status: Suspected
- Affected area: Security
- Evidence:
  - File / path: `server/services/url_security.py:8-34` 校验 scheme、hostname 与首次解析 IP；`server/services/webhook.py` 与 `server/services/effect_webhook.py` 使用默认跟随重定向的 `httpx.post`，未在重定向后重新校验。
  - Relevant behavior: Webhook SSRF 防护可通过重定向绕过
- Problem: Webhook SSRF 防护可通过重定向绕过
- Why it matters: 攻击者可注册公网 HTTPS 端点，302 跳转到内网/metadata 服务，实现 SSRF 或云元数据窃取。
- Realistic failure scenario: 攻击者可注册公网 HTTPS 端点，302 跳转到内网/metadata 服务，实现 SSRF 或云元数据窃取。
- Minimal fix: 禁用重定向或在每次重定向后重新执行 `is_safe_webhook_url`。
- Better long-term fix: 禁用重定向或在每次重定向后重新执行 `is_safe_webhook_url`。
- Regression test suggestion: 配置 302 到 `169.254.169.254` 的 webhook，断言推送被拦截。
- Estimated effort: 2 hours


### Finding: 速率限制中间件无条件信任 X-Forwarded-For

- Severity: High
- Confidence: High
- Category: Security
- Status: Confirmed
- Affected area: Security
- Evidence:
  - File / path: `server/middleware.py:178-183` 直接使用 `X-Forwarded-For` 首个值，未校验可信代理。
  - Relevant behavior: 速率限制中间件无条件信任 X-Forwarded-For
- Problem: 速率限制中间件无条件信任 X-Forwarded-For
- Why it matters: 直接暴露或无信任代理时，客户端可伪造 IP 绕过限流与暴力破解防护。
- Realistic failure scenario: 直接暴露或无信任代理时，客户端可伪造 IP 绕过限流与暴力破解防护。
- Minimal fix: 增加可信代理列表；无信任代理时使用 `request.client.host`；校验 XFF 链。
- Better long-term fix: 增加可信代理列表；无信任代理时使用 `request.client.host`；校验 XFF 链。
- Regression test suggestion: 伪造 X-Forwarded-For 高频请求，限流仍基于真实连接 IP。
- Estimated effort: 2 hours


### Finding: 发送任务启动存在竞态，可创建多个并发发送任务

- Severity: High
- Confidence: High
- Category: Data Integrity
- Status: Confirmed
- Affected area: Data Integrity
- Evidence:
  - File / path: `server/api/industries.py:752-804` 与 `server/api/jobs.py:605-649` 先查询是否有 running send job，再调用 `run_send_job()`，两步非原子。
  - Relevant behavior: 发送任务启动存在竞态，可创建多个并发发送任务
- Problem: 发送任务启动存在竞态，可创建多个并发发送任务
- Why it matters: 快速双击或并行 API 调用会产生多个 running send job，设备被重复申领导致超发。
- Realistic failure scenario: 快速双击或并行 API 调用会产生多个 running send job，设备被重复申领导致超发。
- Minimal fix: 使用数据库唯一部分索引 `(user_id, type, status)` 在 `status IN ('running','cancelling')` 时阻止重复插入；或获取 advisory lock。
- Better long-term fix: 使用数据库唯一部分索引 `(user_id, type, status)` 在 `status IN ('running','cancelling')` 时阻止重复插入；或获取 advisory lock。
- Regression test suggestion: 并行两次 POST `/api/industries/{id}/send`，断言仅有一个 running job。
- Estimated effort: 2 days


### Finding: 设备日/小时发送限额在并发申领下可被突破

- Severity: High
- Confidence: High
- Category: Data Integrity
- Status: Confirmed
- Affected area: Data Integrity
- Evidence:
  - File / path: `core/task/scheduler.py:196-205` 读取 `ConsumerState` 检查限额；`core/task/scheduler.py:225-253` 在 `mark_task_done()` 中增量，二者不在同一事务。
  - Relevant behavior: 设备日/小时发送限额在并发申领下可被突破
- Problem: 设备日/小时发送限额在并发申领下可被突破
- Why it matters: 多个 worker 同时看到未达限额而各自申领，实际发送数超过平台风控阈值。
- Realistic failure scenario: 多个 worker 同时看到未达限额而各自申领，实际发送数超过平台风控阈值。
- Minimal fix: 在申领事务中使用 `UPDATE … SET daily_sent = daily_sent + 1 WHERE daily_sent < limit` 或 `SELECT FOR UPDATE`。
- Better long-term fix: 在申领事务中使用 `UPDATE … SET daily_sent = daily_sent + 1 WHERE daily_sent < limit` 或 `SELECT FOR UPDATE`。
- Regression test suggestion: 两并发 claim-and-complete 针对同一设备且限额为 1，第二个 claim 应被拒绝。
- Estimated effort: 2 days


### Finding: Jobs list 在 normalized status 过滤时绕过数据库分页

- Severity: High
- Confidence: High
- Category: Backend API
- Status: Confirmed
- Affected area: Backend API / Performance
- Evidence:
  - File / path: `server/api/jobs.py:404-413` 对 `sent` / `restricted` / `unconfirmed` 状态使用 `jobs_query.all()` 在 Python 中过滤。
  - Relevant behavior: Jobs list 在 normalized status 过滤时绕过数据库分页
- Problem: Jobs list 在 normalized status 过滤时绕过数据库分页
- Why it matters: 大量历史任务时内存占用与响应时间线性增长，可能 OOM。
- Realistic failure scenario: 大量历史任务时内存占用与响应时间线性增长，可能 OOM。
- Minimal fix: 将 normalized status 过滤下推到数据库，或在内存过滤前先分页。
- Better long-term fix: 将 normalized status 过滤下推到数据库，或在内存过滤前先分页。
- Regression test suggestion: 创建 500 条 job，请求 `/api/jobs?status=sent&limit=10`，验证响应时间与行数有界。
- Estimated effort: 2 hours


### Finding: FastAPI 无 lifespan/shutdown hook，引擎与后台线程泄漏

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `server/main.py:49` 创建 `FastAPI` 未传 `lifespan`；`server/models/__init__.py:14` 模块级 `engine`；`server/middleware.py:157-167` 持久保存 Redis client；`server/workers.py:1026-1035` 自动恢复守护线程无停止机制。
  - Relevant behavior: FastAPI 无 lifespan/shutdown hook，引擎与后台线程泄漏
- Problem: FastAPI 无 lifespan/shutdown hook，引擎与后台线程泄漏
- Why it matters: Uvicorn reload/容器停止时 DB 连接、Redis 连接、后台线程未清理；线程被中断可能导致 job 状态损坏。
- Realistic failure scenario: Uvicorn reload/容器停止时 DB 连接、Redis 连接、后台线程未清理；线程被中断可能导致 job 状态损坏。
- Minimal fix: 添加 `@asynccontextmanager` lifespan，在 shutdown 时 `engine.dispose()`、关闭 Redis、通知恢复线程退出。
- Better long-term fix: 添加 `@asynccontextmanager` lifespan，在 shutdown 时 `engine.dispose()`、关闭 Redis、通知恢复线程退出。
- Regression test suggestion: 启动服务、请求一次、触发 shutdown，验证 engine pool 已 dispose 且线程已 join。
- Estimated effort: 2 days


### Finding: Celery 任务声明 retry 却未触发重试

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `adapters/celery/collect.py:20-26`、`adapters/celery/send.py:19-27`、`adapters/celery/classify.py:18-23` 设置了 `max_retries` 但未设置 `autoretry_for` 也未调用 `self.retry()`。
  - Relevant behavior: Celery 任务声明 retry 却未触发重试
- Problem: Celery 任务声明 retry 却未触发重试
- Why it matters: 瞬态 broker/DB/HTTP/子进程失败永久失败，丢失任务。
- Realistic failure scenario: 瞬态 broker/DB/HTTP/子进程失败永久失败，丢失任务。
- Minimal fix: 为每个任务添加 `autoretry_for` 或在异常处显式调用 `self.retry(countdown=…)`。
- Better long-term fix: 为每个任务添加 `autoretry_for` 或在异常处显式调用 `self.retry(countdown=…)`。
- Regression test suggestion: Mock 任务内部函数先抛 `httpx.ConnectError` 再成功，验证最终成功且被重试。
- Estimated effort: 2 hours


### Finding: Webhook 出站推送无签名、无重试、无幂等键

- Severity: High
- Confidence: High
- Category: Data Integrity
- Status: Confirmed
- Affected area: Data Integrity / Stability
- Evidence:
  - File / path: `server/services/webhook.py:35-82` 与 `server/services/effect_webhook.py:14-55` 直接 `httpx.post` 且无 HMAC 签名、无 `Idempotency-Key`、无投递日志。
  - Relevant behavior: Webhook 出站推送无签名、无重试、无幂等键
- Problem: Webhook 出站推送无签名、无重试、无幂等键
- Why it matters: 接收方无法验证来源；临时故障导致事件永久丢失；重复触发可能重复投递。
- Realistic failure scenario: 接收方无法验证来源；临时故障导致事件永久丢失；重复触发可能重复投递。
- Minimal fix: 使用 `THUNDER_WEBHOOK_SECRET` 生成 HMAC-SHA256 签名；添加幂等键；持久化投递记录与重试。
- Better long-term fix: 使用 `THUNDER_WEBHOOK_SECRET` 生成 HMAC-SHA256 签名；添加幂等键；持久化投递记录与重试。
- Regression test suggestion: Mock 接收方验证签名；同一 payload 同一 idempotency key 应被去重。
- Estimated effort: 2 days


### Finding: 全局 OpenAI reply client 跨 DeviceWorker 线程无同步

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `core/task/worker.py:23-40` 模块级 `_reply_client` 与 `_loaded_reply_key` 在 `_get_reply_client()` 中无锁修改。
  - Relevant behavior: 全局 OpenAI reply client 跨 DeviceWorker 线程无同步
- Problem: 全局 OpenAI reply client 跨 DeviceWorker 线程无同步
- Why it matters: 并发发送线程竞争创建/覆盖 client，导致 API key 串用或连接泄漏。
- Realistic failure scenario: 并发发送线程竞争创建/覆盖 client，导致 API key 串用或连接泄漏。
- Minimal fix: 使用 `threading.Lock` 保护创建，或为每个 `DeviceWorker` 实例持有独立 client。
- Better long-term fix: 使用 `threading.Lock` 保护创建，或为每个 `DeviceWorker` 实例持有独立 client。
- Regression test suggestion: 多线程并发使用不同 `deepseek_key` 创建 worker，断言各用各的 key。
- Estimated effort: 2 hours


### Finding: 全局 classification router 懒加载无线程安全

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `core/classify.py:457` 模块级 `_router`；`494-496` 懒初始化。
  - Relevant behavior: 全局 classification router 懒加载无线程安全
- Problem: 全局 classification router 懒加载无线程安全
- Why it matters: 多线程 Celery worker 并发调用时可能初始化出混合 backend/client。
- Realistic failure scenario: 多线程 Celery worker 并发调用时可能初始化出混合 backend/client。
- Minimal fix: 每次调用实例化 router，或使用锁/thread-local 保护初始化。
- Better long-term fix: 每次调用实例化 router，或使用锁/thread-local 保护初始化。
- Regression test suggestion: 多线程并发 `classify_batch` 使用不同 `llm_client`，断言无跨线程泄漏。
- Estimated effort: 2 hours


### Finding: Celery collect 任务在已有事件循环时调用 asyncio.run

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `adapters/celery/collect.py:38` 使用 `asyncio.run(run_platform(...))`。
  - Relevant behavior: Celery collect 任务在已有事件循环时调用 asyncio.run
- Problem: Celery collect 任务在已有事件循环时调用 asyncio.run
- Why it matters: 在已有事件循环的线程（gevent、嵌套调用）中会抛 `RuntimeError` 并崩溃。
- Realistic failure scenario: 在已有事件循环的线程（gevent、嵌套调用）中会抛 `RuntimeError` 并崩溃。
- Minimal fix: 使用 `asyncio.get_event_loop()` / `new_event_loop()` 保护，或声明 Celery async 任务。
- Better long-term fix: 使用 `asyncio.get_event_loop()` / `new_event_loop()` 保护，或声明 Celery async 任务。
- Regression test suggestion: 在已有事件循环的线程中调用 `run_mediacrawler.delay(...)`，断言成功完成。
- Estimated effort: 2 days


### Finding: 分类管道吞掉所有后端失败并返回空

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `core/classify.py:497-506` `except Exception` 直接 `return passed`。
  - Relevant behavior: 分类管道吞掉所有后端失败并返回空
- Problem: 分类管道吞掉所有后端失败并返回空
- Why it matters: unexpected Dify/DirectLLM 错误导致全部候选评论被丢弃，无重试或死信路径。
- Realistic failure scenario: unexpected Dify/DirectLLM 错误导致全部候选评论被丢弃，无重试或死信路径。
- Minimal fix: 区分瞬态与永久错误；瞬态重试；永久错误保留候选以便后续处理。
- Better long-term fix: 区分瞬态与永久错误；瞬态重试；永久错误保留候选以便后续处理。
- Regression test suggestion: Mock 两个 backend 均抛异常，断言异常被上报或候选被保留。
- Estimated effort: 2 hours


### Finding: Dify batch 失败静默丢弃线索

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `adapters/dify/client.py:161-164` `except Exception: log.warning; continue`。
  - Relevant behavior: Dify batch 失败静默丢弃线索
- Problem: Dify batch 失败静默丢弃线索
- Why it matters: 一批评论分类失败后整批丢失，caller 只拿到成功批次。
- Realistic failure scenario: 一批评论分类失败后整批丢失，caller 只拿到成功批次。
- Minimal fix: 记录每批失败并返回部分失败标志，或回退到 DirectLLM 重新分类。
- Better long-term fix: 记录每批失败并返回部分失败标志，或回退到 DirectLLM 重新分类。
- Regression test suggestion: Mock Dify 三批中一批失败，断言失败批次被 fallback 且总数正确。
- Estimated effort: 2 hours


### Finding: 批量入队将任意 DB 失败当作重复

- Severity: High
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability / Data Integrity
- Evidence:
  - File / path: `server/services/task_stats.py:805-808` `except Exception` 回滚后返回 `duplicates: valid`。
  - Relevant behavior: 批量入队将任意 DB 失败当作重复
- Problem: 批量入队将任意 DB 失败当作重复
- Why it matters: DB 中断/锁超时等真实故障被掩盖为重复，导致数据丢失且不会重试。
- Realistic failure scenario: DB 中断/锁超时等真实故障被掩盖为重复，导致数据丢失且不会重试。
- Minimal fix: 仅捕获 integrity error 作为重复，其他 `SQLAlchemyError` 单独报错。
- Better long-term fix: 仅捕获 integrity error 作为重复，其他 `SQLAlchemyError` 单独报错。
- Regression test suggestion: Mock `db.execute` 抛 `OperationalError`，断言返回失败而非重复。
- Estimated effort: 2 hours


### Finding: Health endpoint 需要认证但 docker-compose healthcheck 未带认证

- Severity: High
- Confidence: High
- Category: Configuration
- Status: Confirmed
- Affected area: Configuration / Observability
- Evidence:
  - File / path: `server/api/stats.py:170-173` 的 `/api/system/health` 依赖 `get_current_user`；`docker-compose.yml:65` 使用 `urllib.request.urlopen('http://localhost:8000/api/system/health')` 无认证头。
  - Relevant behavior: Health endpoint 需要认证但 docker-compose healthcheck 未带认证
- Problem: Health endpoint 需要认证但 docker-compose healthcheck 未带认证
- Why it matters: 容器健康检查收到 401，Docker 判定服务 unhealthy 并不断重启。
- Realistic failure scenario: 容器健康检查收到 401，Docker 判定服务 unhealthy 并不断重启。
- Minimal fix: 暴露 `/healthz` 免认证内部探针，或更新 compose healthcheck 使用带 internal token 的路径。
- Better long-term fix: 暴露 `/healthz` 免认证内部探针，或更新 compose healthcheck 使用带 internal token 的路径。
- Regression test suggestion: `docker compose up -d` 后 `docker compose ps` 显示 server healthy。
- Estimated effort: 30 minutes


### Finding: 系统配置与环境变量无 schema 校验

- Severity: High
- Confidence: High
- Category: Configuration
- Status: Confirmed
- Affected area: Configuration
- Evidence:
  - File / path: `core/config.py:30-40` 仅做 `${VAR}` 替换；`86-104` 用 `yaml.safe_load` 读 `system.yaml` 无模型校验；`server/config.py:14-63` 仅校验生产环境 `THUNDER_SECRET_KEY`。
  - Relevant behavior: 系统配置与环境变量无 schema 校验
- Problem: 系统配置与环境变量无 schema 校验
- Why it matters: 拼写错误、缺失变量、非法 URL 到运行时才暴露，导致启动崩溃或静默错误配置。
- Realistic failure scenario: 拼写错误、缺失变量、非法 URL 到运行时才暴露，导致启动崩溃或静默错误配置。
- Minimal fix: 引入 Pydantic `BaseSettings` 与 `system.yaml` Pydantic model，启动时校验并快速失败。
- Better long-term fix: 引入 Pydantic `BaseSettings` 与 `system.yaml` Pydantic model，启动时校验并快速失败。
- Regression test suggestion: 提供错误配置启动，断言得到清晰 `ValidationError`。
- Estimated effort: 2 days


### Finding: 架构分层边界被大量违反

- Severity: High
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: Maintainability / Design
- Evidence:
  - File / path: `core/classify.py:25` 导入 `server.services.task_stats`；`core/agent/memory.py:17,32` 导入 `server.models`；`core/task/worker.py:17` 导入 `server.services.abtest`；`core/discover.py:6` 导入 `adapters.mediacrawler.runner`；`core/config.py:131-134` 导入 `server.models` 与 `server.secret_store`；`server/api/devices.py:23` 导入 `scripts.smoke.real_device_acceptance`。
  - Relevant behavior: 架构分层边界被大量违反
- Problem: 架构分层边界被大量违反
- Why it matters: `core` 无法独立单元测试，循环依赖风险，生产代码依赖临时 smoke 脚本。
- Realistic failure scenario: `core` 无法独立单元测试，循环依赖风险，生产代码依赖临时 smoke 脚本。
- Minimal fix: 将共享模型抽到独立 `models/` 包；`core` 通过 port/依赖注入访问 DB；移除 `server -> scripts.smoke` 导入。
- Better long-term fix: 将共享模型抽到独立 `models/` 包；`core` 通过 port/依赖注入访问 DB；移除 `server -> scripts.smoke` 导入。
- Regression test suggestion: 静态 import graph 不存在 `core -> server/adapters` 与 `server -> scripts` 的边。
- Estimated effort: 1 week


### Finding: 多个文件与函数远超推荐规模

- Severity: High
- Confidence: High
- Category: Maintainability
- Status: Confirmed
- Affected area: Maintainability
- Evidence:
  - File / path: `server/api/industries.py` 1360 行、`server/workers.py` 1035 行、`server/services/task_stats.py` 841 行；`core/task/runner.py:183-481` 的 `run_douyin_dm` 299 行、`server/workers.py:597-792` 的 `run_collect_job` 196 行、`core/agent/direct_glm.py:204-391` 的 `execute_plan` 188 行；多处嵌套深度 ≥6。
  - Relevant behavior: 多个文件与函数远超推荐规模
- Problem: 多个文件与函数远超推荐规模
- Why it matters: 认知负荷高、单测困难、隐藏 bug 面大。
- Realistic failure scenario: 认知负荷高、单测困难、隐藏 bug 面大。
- Minimal fix: 按领域拆模块，抽取辅助函数，用早返回降低嵌套。
- Better long-term fix: 按领域拆模块，抽取辅助函数，用早返回降低嵌套。
- Regression test suggestion: 无源文件 >800 行、无函数 >50 行、最大嵌套 ≤4。
- Estimated effort: 1 week


### Finding: Mypy 在关键模块 blanket-ignore 错误

- Severity: High
- Confidence: High
- Category: Type Safety
- Status: Confirmed
- Affected area: Type Safety
- Evidence:
  - File / path: `pyproject.toml:66-83` 对所有 `server.api.*`、`server.workers`、`core.config`、`core.device.supervisor`、`core.agent.perception`、`core.agent.memory`、`core.strategy.policy` 设置 `ignore_errors = true`。
  - Relevant behavior: Mypy 在关键模块 blanket-ignore 错误
- Problem: Mypy 在关键模块 blanket-ignore 错误
- Why it matters: API 表面与核心业务逻辑的类型回归在 CI 中静默通过。
- Realistic failure scenario: API 表面与核心业务逻辑的类型回归在 CI 中静默通过。
- Minimal fix: 移除模块级 `ignore_errors`；逐步修复或改用带 reason 的 `# type: ignore[<code>]`。
- Better long-term fix: 移除模块级 `ignore_errors`；逐步修复或改用带 reason 的 `# type: ignore[<code>]`。
- Regression test suggestion: `mypy server/ core/ adapters/ cli.py` 零错误（或仅含带 reason 的显式忽略）。
- Estimated effort: 1 week


### Finding: 默认 pytest 收集仓库根目录时包含损坏的外部测试

- Severity: High
- Confidence: High
- Category: Testing
- Status: Confirmed
- Affected area: Testing
- Evidence:
  - File / path: `pyproject.toml:92-100` 未设置 `testpaths`/`norecursedirs`；`python -m pytest --co -q` 在根目录报告 6 个 collection error（`deps/MediaCrawler/tests`、`data/mc_failures/…/tests`、`scripts/smoke`）。
  - Relevant behavior: 默认 pytest 收集仓库根目录时包含损坏的外部测试
- Problem: 默认 pytest 收集仓库根目录时包含损坏的外部测试
- Why it matters: 默认 `pytest` 调用与 naïve CI 失败，文档中的命令与实际不一致。
- Realistic failure scenario: 默认 `pytest` 调用与 naïve CI 失败，文档中的命令与实际不一致。
- Minimal fix: 添加 `testpaths = ["tests"]` 与 `norecursedirs = ["deps", "data", "scripts", ".venv", "dist", "build"]`。
- Better long-term fix: 添加 `testpaths = ["tests"]` 与 `norecursedirs = ["deps", "data", "scripts", ".venv", "dist", "build"]`。
- Regression test suggestion: 根目录 `pytest --co -q` 零 error 收集 381 个测试。
- Estimated effort: 30 minutes


### Finding: 共享持久测试数据库缺乏单测隔离

- Severity: High
- Confidence: High
- Category: Testing
- Status: Confirmed
- Affected area: Testing
- Evidence:
  - File / path: `tests/conftest.py:9-12` 设置 `THUNDER_DATABASE_URL=sqlite:///./data/test_thunder.db` 并只在 session 开始时删一次；`tests/server/test_industries.py:17-21` 直接提交/删除行而无回滚。
  - Relevant behavior: 共享持久测试数据库缺乏单测隔离
- Problem: 共享持久测试数据库缺乏单测隔离
- Why it matters: 测试顺序泄漏、 leftover 行导致不稳定，无法安全并行执行。
- Realistic failure scenario: 测试顺序泄漏、 leftover 行导致不稳定，无法安全并行执行。
- Minimal fix: 提供 per-test 内存数据库 fixture，覆盖 `SessionLocal` 与 `get_db`，yield 后 teardown。
- Better long-term fix: 提供 per-test 内存数据库 fixture，覆盖 `SessionLocal` 与 `get_db`，yield 后 teardown。
- Regression test suggestion: `pytest tests/ -p pytest-randomly` 在多种随机顺序下通过。
- Estimated effort: 2 days


### Finding: 未配置测试覆盖率工具

- Severity: High
- Confidence: High
- Category: Testing
- Status: Confirmed
- Affected area: Testing
- Evidence:
  - File / path: `pyproject.toml` 无 coverage 配置；`pytest-cov` 未安装；无 `fail_under`。
  - Relevant behavior: 未配置测试覆盖率工具
- Problem: 未配置测试覆盖率工具
- Why it matters: 80% 覆盖率要求无法落地，回归易逃逸。
- Realistic failure scenario: 80% 覆盖率要求无法落地，回归易逃逸。
- Minimal fix: 添加 `pytest-cov`/`coverage[toml]`，配置 `[tool.coverage.run]` / `[tool.coverage.report]` 并设 `fail_under = 80`。
- Better long-term fix: 添加 `pytest-cov`/`coverage[toml]`，配置 `[tool.coverage.run]` / `[tool.coverage.report]` 并设 `fail_under = 80`。
- Regression test suggestion: `pytest tests/ --cov=core --cov=server --cov=adapters --cov-fail-under=80` 通过。
- Estimated effort: 2 hours


### Finding: GET endpoint 在读取请求中修改 job 状态

- Severity: Medium
- Confidence: High
- Category: Backend API
- Status: Confirmed
- Affected area: Backend API
- Evidence:
  - File / path: `server/api/jobs.py:401-402` 与 `server/api/dashboard.py:264-265` 在 GET handler 中调用 reconciliation 函数。
  - Relevant behavior: GET endpoint 在读取请求中修改 job 状态
- Problem: GET endpoint 在读取请求中修改 job 状态
- Why it matters: 读取非幂等、调试困难、多进程下重复协调。
- Realistic failure scenario: 读取非幂等、调试困难、多进程下重复协调。
- Minimal fix: 将协调逻辑移到后台调度或 auto-recovery 线程，从 GET handler 移除。
- Better long-term fix: 将协调逻辑移到后台调度或 auto-recovery 线程，从 GET handler 移除。
- Regression test suggestion: 两次调用 `/api/jobs` 对健康 job 无状态变化。
- Estimated effort: 2 hours


### Finding: Device scan 在循环内逐设备 commit

- Severity: Medium
- Confidence: High
- Category: Data Integrity
- Status: Confirmed
- Affected area: Data Integrity
- Evidence:
  - File / path: `server/api/devices.py:485-530` 在循环中多次 `db.commit()`。
  - Relevant behavior: Device scan 在循环内逐设备 commit
- Problem: Device scan 在循环内逐设备 commit
- Why it matters: ADB 或 DB 错误导致部分设备已注册、部分缺失，无法原子回滚。
- Realistic failure scenario: ADB 或 DB 错误导致部分设备已注册、部分缺失，无法原子回滚。
- Minimal fix: 循环内只收集对象，循环外一次 commit。
- Better long-term fix: 循环内只收集对象，循环外一次 commit。
- Regression test suggestion: 注入中途失败，断言无设备被持久化。
- Estimated effort: 30 minutes


### Finding: Industry delete 的清理与软删分两次 commit

- Severity: Medium
- Confidence: High
- Category: Data Integrity
- Status: Confirmed
- Affected area: Data Integrity
- Evidence:
  - File / path: `server/api/industries.py:651-673` 先 commit 清理，再 commit 软删。
  - Relevant behavior: Industry delete 的清理与软删分两次 commit
- Problem: Industry delete 的清理与软删分两次 commit
- Why it matters: 第二次 commit 失败时行业仍 active 但数据已清理，状态不一致。
- Realistic failure scenario: 第二次 commit 失败时行业仍 active 但数据已清理，状态不一致。
- Minimal fix: 所有操作在同一事务内，只 commit 一次。
- Better long-term fix: 所有操作在同一事务内，只 commit 一次。
- Regression test suggestion: Mock 最终 commit 失败，断言清理被回滚。
- Estimated effort: 30 minutes


### Finding: 重试过滤用字符串比较 ISO datetime

- Severity: Medium
- Confidence: High
- Category: Data Integrity
- Status: Confirmed
- Affected area: Data Integrity
- Evidence:
  - File / path: `server/api/industries.py:868-872` 对 `String` 列 `TaskQueue.retry_after` 与 `datetime.now().isoformat()` 做字典序比较。
  - Relevant behavior: 重试过滤用字符串比较 ISO datetime
- Problem: 重试过滤用字符串比较 ISO datetime
- Why it matters: 时区/格式差异导致应冷却的任务被放出或应就绪的任务被隐藏。
- Realistic failure scenario: 时区/格式差异导致应冷却的任务被放出或应就绪的任务被隐藏。
- Minimal fix: 将列改为 `DateTime` 或在比较前解析为 `datetime`。
- Better long-term fix: 将列改为 `DateTime` 或在比较前解析为 `datetime`。
- Regression test suggestion: 混合 `Z` 与 `+00:00` 格式任务，断言过滤结果正确。
- Estimated effort: 2 hours


### Finding: Dashboard 执行监控对每个设备发两次查询

- Severity: Medium
- Confidence: High
- Category: Backend API
- Status: Confirmed
- Affected area: Backend API / Performance
- Evidence:
  - File / path: `server/api/dashboard.py:401-460` 循环设备状态，每次查询最新 `ExecutionLog` 与 `ScreenSnapshot`。
  - Relevant behavior: Dashboard 执行监控对每个设备发两次查询
- Problem: Dashboard 执行监控对每个设备发两次查询
- Why it matters: `1 + 2N` 查询，延迟随设备数线性增长。
- Realistic failure scenario: `1 + 2N` 查询，延迟随设备数线性增长。
- Minimal fix: 用 `ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY created_at DESC)` 一次取最新记录。
- Better long-term fix: 用 `ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY created_at DESC)` 一次取最新记录。
- Regression test suggestion: 查询数与设备数无关。
- Estimated effort: 2 days


### Finding: API 错误响应结构不一致

- Severity: Medium
- Confidence: High
- Category: Backend API
- Status: Confirmed
- Affected area: Backend API
- Evidence:
  - File / path: `server/api/auth.py:76-79` 与 `server/api/jobs.py:517` 抛 `HTTPException` 返回 `{"detail": ...}`；`server/api/devices.py:52-58` 抛 `AppError` 经 `server/main.py:61-67` 序列化为 `{"ok": false, "code": ...}`。
  - Relevant behavior: API 错误响应结构不一致
- Problem: API 错误响应结构不一致
- Why it matters: 客户端需处理两种错误形状，集成脆弱。
- Realistic failure scenario: 客户端需处理两种错误形状，集成脆弱。
- Minimal fix: 为 `HTTPException` 注册统一异常 handler 映射到 `AppError` 信封，或全部改用 `AppError`。
- Better long-term fix: 为 `HTTPException` 注册统一异常 handler 映射到 `AppError` 信封，或全部改用 `AppError`。
- Regression test suggestion: 触发 auth/devices/jobs 错误路径，断言返回统一结构。
- Estimated effort: 2 hours


### Finding: Leads endpoint 静默吞掉数据库错误

- Severity: Medium
- Confidence: High
- Category: Backend API
- Status: Confirmed
- Affected area: Backend API
- Evidence:
  - File / path: `server/api/leads.py:131-152` 与 `155-173` 捕获所有异常返回空列表。
  - Relevant behavior: Leads endpoint 静默吞掉数据库错误
- Problem: Leads endpoint 静默吞掉数据库错误
- Why it matters: DB 故障被伪装成空数据，掩盖运营问题。
- Realistic failure scenario: DB 故障被伪装成空数据，掩盖运营问题。
- Minimal fix: 记录异常并作为 500 抛出；仅对真正空结果返回空列表。
- Better long-term fix: 记录异常并作为 500 抛出；仅对真正空结果返回空列表。
- Regression test suggestion: Patch `SessionLocal` 抛异常，断言返回 500。
- Estimated effort: 30 minutes


### Finding: Matrix 任务重试退避无上限、无最大次数

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `core/task/scheduler.py:403-414` 使用 `5 * (3 ** current_retries)`（5, 15, 45, 135… 分钟）。
  - Relevant behavior: Matrix 任务重试退避无上限、无最大次数
- Problem: Matrix 任务重试退避无上限、无最大次数
- Why it matters: 永久失败的任务无限后延，backlog 膨胀，retry_after 可达数天。
- Realistic failure scenario: 永久失败的任务无限后延，backlog 膨胀，retry_after 可达数天。
- Minimal fix: 限制 `retry_count <= 5`，`cooldown_minutes <= 60`，超限转 `failed`。
- Better long-term fix: 限制 `retry_count <= 5`，`cooldown_minutes <= 60`，超限转 `failed`。
- Regression test suggestion: 调用 `mark_task_retry` 6 次，断言 retry_count 停在 5 且状态变 failed。
- Estimated effort: 2 hours


### Finding: DeviceWorker 无视 Celery soft time limit 继续发送

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `adapters/celery/send.py:19-23` 设置 `soft_time_limit=600`；`core/task/worker.py:173-301` 的 `DeviceWorker.run()` 无耗时检查。
  - Relevant behavior: DeviceWorker 无视 Celery soft time limit 继续发送
- Problem: DeviceWorker 无视 Celery soft time limit 继续发送
- Why it matters: 高 daily_limit 或慢间隔下 Celery 在发送中途被 kill，任务状态可能损坏。
- Realistic failure scenario: 高 daily_limit 或慢间隔下 Celery 在发送中途被 kill，任务状态可能损坏。
- Minimal fix: 在 `run()` 中记录 `started_at`，在达到 soft limit 80% 前安全退出。
- Better long-term fix: 在 `run()` 中记录 `started_at`，在达到 soft limit 80% 前安全退出。
- Regression test suggestion: 模拟慢发送，断言 worker 在 limit 前干净退出。
- Estimated effort: 2 hours


### Finding: DirectGLM 每步发送全量 base64 截图

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability / Performance
- Evidence:
  - File / path: `core/agent/direct_glm.py:151-178` 每步将截图转 base64 并 POST，且 `MAX_TOTAL_ACTIONS = 30`。
  - Relevant behavior: DirectGLM 每步发送全量 base64 截图
- Problem: DirectGLM 每步发送全量 base64 截图
- Why it matters: vision model 调用成本远高于文本，快速消耗 LLM 预算。
- Realistic failure scenario: vision model 调用成本远高于文本，快速消耗 LLM 预算。
- Minimal fix: 压缩/缩放截图、无变化时复用缓存、优先使用 OCR/文本状态表示。
- Better long-term fix: 压缩/缩放截图、无变化时复用缓存、优先使用 OCR/文本状态表示。
- Regression test suggestion: 测量每步字节数并设阈值。
- Estimated effort: 2 days


### Finding: Celery collect pipeline 下游任务被注释

- Severity: Medium
- Confidence: High
- Category: Stability
- Status: Confirmed
- Affected area: Stability
- Evidence:
  - File / path: `adapters/celery/collect.py:48-70` 的 `chain()` 中 `classify_batch.s()` 与 `enqueue_classified.s()` 被注释。
  - Relevant behavior: Celery collect pipeline 下游任务被注释
- Problem: Celery collect pipeline 下游任务被注释
- Why it matters: Celery 采集任务只抓取不分类不入队，无法产生可用线索。
- Realistic failure scenario: Celery 采集任务只抓取不分类不入队，无法产生可用线索。
- Minimal fix: 恢复并加错误处理的链路，或在就绪前移除未完成的 orchestrator。
- Better long-term fix: 恢复并加错误处理的链路，或在就绪前移除未完成的 orchestrator。
- Regression test suggestion: 调用 `run_full_collection.delay(...)` 断言后续任务被触发。
- Estimated effort: 2 hours


### Finding: 无应用指标或告警端点

- Severity: Medium
- Confidence: High
- Category: Observability
- Status: Confirmed
- Affected area: Observability
- Evidence:
  - File / path: `server/` 与 `core/` 中无 `prometheus`、`/metrics`、Counter、Histogram；`server/api/stats.py` 仅提供健康。
  - Relevant behavior: 无应用指标或告警端点
- Problem: 无应用指标或告警端点
- Why it matters: 无法监控吞吐量、错误率、队列深度、设备发送成功率，无法配置告警。
- Realistic failure scenario: 无法监控吞吐量、错误率、队列深度、设备发送成功率，无法配置告警。
- Minimal fix: 增加 `/metrics` 与 `prometheus-client`，在关键路径埋点。
- Better long-term fix: 增加 `/metrics` 与 `prometheus-client`，在关键路径埋点。
- Regression test suggestion: `curl /metrics` 返回非空且含 `thunder_` 前缀指标。
- Estimated effort: 2 days


### Finding: 日志打印敏感 URL 与密钥未脱敏

- Severity: Medium
- Confidence: High
- Category: Observability
- Status: Confirmed
- Affected area: Observability / Security
- Evidence:
  - File / path: `core/redis.py:42` 打印完整 Redis URL（可能含密码）；`server/services/webhook.py:75` 与 `server/services/effect_webhook.py:51` 打印完整 webhook_url；`core/proxy.py:72` 打印 `proxy[:40]` 可能含认证信息。
  - Relevant behavior: 日志打印敏感 URL 与密钥未脱敏
- Problem: 日志打印敏感 URL 与密钥未脱敏
- Why it matters: 凭据、签名 webhook URL、API key 进入日志文件与 stdout，扩大泄露面。
- Realistic failure scenario: 凭据、签名 webhook URL、API key 进入日志文件与 stdout，扩大泄露面。
- Minimal fix: 日志前剥离 URL userinfo/query token；API key 使用 `mask_secret()`；增加 redaction filter。
- Better long-term fix: 日志前剥离 URL userinfo/query token；API key 使用 `mask_secret()`；增加 redaction filter。
- Regression test suggestion: 配置含密码的 Redis URL，触发连接失败，验证日志中无密码。
- Estimated effort: 2 hours


### Finding: README 快速开始指向不存在的路径

- Severity: Medium
- Confidence: High
- Category: Documentation
- Status: Confirmed
- Affected area: Documentation
- Evidence:
  - File / path: `README.md:83-89` 写 `pip install -r requirements.txt` / `requirements-server.txt`，实际为 `requirements/base.txt` / `requirements/server.txt`；`README.md:88` 写 `cd Open-AutoGLM`，实际为 `deps/Open-AutoGLM`。
  - Relevant behavior: README 快速开始指向不存在的路径
- Problem: README 快速开始指向不存在的路径
- Why it matters: 新贡献者与自动化安装按 README 执行会 `FileNotFoundError`。
- Realistic failure scenario: 新贡献者与自动化安装按 README 执行会 `FileNotFoundError`。
- Minimal fix: 更新 README 路径或推荐使用 `pip install -e .[dev,adapters]`。
- Better long-term fix: 更新 README 路径或推荐使用 `pip install -e .[dev,adapters]`。
- Regression test suggestion: 新 clone 按 README 执行至安装完成无报错。
- Estimated effort: 30 minutes


### Finding: PROJECT_STRUCTURE 架构声明与实际依赖图矛盾

- Severity: Medium
- Confidence: High
- Category: Documentation
- Status: Confirmed
- Affected area: Documentation / Design
- Evidence:
  - File / path: `PROJECT_STRUCTURE.md:104-108` 称 `core/` 无外部依赖、`adapters/` 只依赖外部服务；实际存在大量 `core -> server/adapters` 与 `server -> scripts.smoke` 导入。
  - Relevant behavior: PROJECT_STRUCTURE 架构声明与实际依赖图矛盾
- Problem: PROJECT_STRUCTURE 架构声明与实际依赖图矛盾
- Why it matters: 文档误导开发者与 reviewer 对模块边界的判断。
- Realistic failure scenario: 文档误导开发者与 reviewer 对模块边界的判断。
- Minimal fix: 重构以符合文档，或更新文档反映真实依赖图。
- Better long-term fix: 重构以符合文档，或更新文档反映真实依赖图。
- Regression test suggestion: 自动 import graph 检查与文档一致。
- Estimated effort: S（文档）/ L（重构）


### Finding: Acceptance evidence endpoint 在未提供 report_path 时未校验所有权

- Severity: Low
- Confidence: Medium
- Category: Security
- Status: Suspected
- Affected area: Security
- Evidence:
  - File / path: `server/api/devices.py:178-216` 仅在提供 `report_path` 时校验所有权，否则返回 `data/acceptance` 下任意解析后文件。
  - Relevant behavior: Acceptance evidence endpoint 在未提供 report_path 时未校验所有权
- Problem: Acceptance evidence endpoint 在未提供 report_path 时未校验所有权
- Why it matters: 知道/猜到他人 evidence UUID 路径的用户可能下载其他租户截图。
- Realistic failure scenario: 知道/猜到他人 evidence UUID 路径的用户可能下载其他租户截图。
- Minimal fix: 始终要求 `report_path` 并校验 `user_id` 与 `evidence_files` 白名单。
- Better long-term fix: 始终要求 `report_path` 并校验 `user_id` 与 `evidence_files` 白名单。
- Regression test suggestion: 无 report_path 时请求他人 evidence UUID，返回 403。
- Estimated effort: 2 hours


### Finding: CSV/XLSX 导出可能包含公式注入载荷

- Severity: Low
- Confidence: Medium
- Category: Security
- Status: Suspected
- Affected area: Security
- Evidence:
  - File / path: `server/services/export.py:53-77` 未对前导 `=`、`+`、`-`、`@` 做清洗。
  - Relevant behavior: CSV/XLSX 导出可能包含公式注入载荷
- Problem: CSV/XLSX 导出可能包含公式注入载荷
- Why it matters: 打开导出文件可能执行嵌入公式，造成客户端 RCE 或数据外泄。
- Realistic failure scenario: 打开导出文件可能执行嵌入公式，造成客户端 RCE 或数据外泄。
- Minimal fix: 对导出内容加 `'` 前缀或设置 `openpyxl` cell data type。
- Better long-term fix: 对导出内容加 `'` 前缀或设置 `openpyxl` cell data type。
- Regression test suggestion: 导出 `text` 以 `=cmd|' /C calc'!A0` 开头，验证输出被清洗。
- Estimated effort: 30 minutes

## 5. Dimension-specific Sections

### 5.1 Security Concerns

- Coverage: High
- Inspected evidence: `server/auth.py`, `server/middleware.py`, `server/api/*.py`, `core/classify.py`, `core/task/worker.py`, `server/secret_store.py`, `.env`, `server/config.py`
- Exclusions / limits: vendored Open-AutoGLM 内部未完整审计；前端 SPA 未深入

| Subtype | Count | Affected Surface | Recommended Action |
|---------|-------|------------------|-------------------|
| Auth/Multi-tenancy | 6 | `Industry.slug`, `TaskQueue.owner_user_id`, Celery tasks, delete cleanup | 加 `(user_id, slug)` 唯一约束；任务携带 user_id；owner 列 non-nullable |
| Secrets management | 4 | `.env`, `THUNDER_ENCRYPTION_KEY`, LLM client cache, logs | 删除 `.env`、轮换密钥、独立加密密钥、日志脱敏 |
| Input validation / Injection | 3 | LLM prompts, webhook URL, lead export fields | prompt 隔离、webhook 重定向校验、导出字段白名单 |
| LLM-related security | 3 | Reply generation, phone agent actions, prompt injection | 内容审核、动作白名单/校验、prompt 隔离 |
| Rate limiting / CORS / Headers | 3 | `X-Forwarded-For`, CORS wildcard, CSP/HSTS | 可信代理、拒绝 wildcard credentials、加 CSP |

### 5.2 Stability Concerns

- Coverage: High
- Inspected evidence: Celery tasks, `core/task/scheduler.py`, `core/task/worker.py`, `adapters/dify/client.py`, `server/workers.py`, `server/main.py`, `adapters/mediacrawler/runner.py`, `core/device/supervisor.py`, `server/services/webhook.py`
- Exclusions / limits: 未在生产负载下压测

| Subtype | Count | Critical Signals Missing | Recommended Action |
|---------|-------|--------------------------|-------------------|
| Error handling / Silent swallow | 8 | classification, Dify, enqueue, supervisor, leads, MediaCrawler | 区分异常类型，记录并上报真实错误 |
| Concurrency / Race conditions | 6 | send job start, device limits, global clients, quota reservation | 原子操作/唯一索引/SELECT FOR UPDATE |
| Retry / Backoff | 5 | Celery tasks, DirectGLM, webhooks, MediaCrawler | 设置 `autoretry_for` / tenacity / 指数退避 |
| Resource lifecycle | 4 | FastAPI lifespan, DB engine, Redis, daemon threads | 添加 lifespan shutdown hook |
| Timeouts / Deadlines | 3 | LLM calls, DeviceWorker, MediaCrawler | 单调用 timeout、Celery soft limit 检查、整体 deadline |

### 5.3 Performance Concerns

- Coverage: Medium
- Inspected evidence: `server/api/dashboard.py`, `server/api/jobs.py`, `core/task/scheduler.py`, `core/agent/direct_glm.py`, `core/discover.py`
- Exclusions / limits: 未做真实 profiling

| Subtype | Count | Cost Driver | Recommended Action |
|---------|-------|-------------|-------------------|
| N+1 queries | 2 | Dashboard / Jobs endpoints | 窗口函数批量取最新记录 |
| Unbounded queries | 1 | Jobs normalized status filter | 下推过滤或先分页 |
| LLM cost | 2 | Full base64 screenshots, no token tracking | 压缩/缓存截图、记录 usage、预算上限 |
| Retry backoff | 1 | Uncapped 3^n cooldown | 限制重试次数与最大冷却 |

### 5.4 Testing Gaps

- Coverage: High
- Inspected evidence: `tests/`, `pyproject.toml`, `pytest` run, `ruff`, `mypy`
- Exclusions / limits: 未逐行阅读全部 381 个测试

| Subtype | Count | Affected Tests | Recommended Action |
|---------|-------|----------------|-------------------|
| Test configuration | 2 | pytest `testpaths`, coverage | 设置 `testpaths`、添加 pytest-cov + 80% gate |
| Test isolation | 1 | Shared persistent test DB | per-test in-memory DB fixture |
| Test quality | 3 | Private impl tests, sleeps, call-order assertions | 测公共行为、事件同步替代 sleep |
| Markers | 1 | real_device / e2e 未使用 | 正确标记硬件/浏览器测试 |

### 5.5 Maintainability Concerns

- Coverage: High
- Inspected evidence: Import graph, file sizes, function lengths, docstrings, ruff/mypy output
- Exclusions / limits: 未使用自动化 import-graph 工具

| Subtype | Count | Affected Areas | Recommended Action |
|---------|-------|----------------|-------------------|
| Architecture boundary violations | 1 | `core -> server/adapters`, `server -> scripts.smoke` | 提取共享模型包、依赖注入 |
| File/function size | 1 | `server/api/industries.py`, `server/workers.py`, `core/task/runner.py` 等 | 拆分模块、抽取辅助函数 |
| Deep nesting | 1 | `direct_glm.py`, `industries.py`, `discover.py`, `worker.py` | 早返回降低嵌套 |
| Documentation | 2 | Missing docstrings, stale README/PROJECT_STRUCTURE | 补 docstring、更新文档或重构以符合文档 |
| Code consistency | 1 | Ruff unconfigured | 配置 ruff 规则并在 CI 强制执行 |

### 5.6 Design / Principles Concerns

- Coverage: Medium
- Inspected evidence: Layer dependency direction, SRP, fail-fast, immutability claims from coding-style rules
- Exclusions / limits: 未做完整设计走查

| Subtype | Count | Affected Areas | Recommended Action |
|---------|-------|----------------|-------------------|
| Dependency direction | 1 | `core` 依赖 `server`/`adapters` | 反转依赖，引入 port/adapter |
| SRP | 1 | 超大文件/函数 | 拆分 |
| Fail-fast | 1 | 配置无校验、错误静默吞掉 | 启动校验、区分错误处理 |

### 5.7 Release Concerns

- Coverage: High
- Inspected evidence: `.github/workflows/*.yml`, `Dockerfile.*`, `docker-compose.yml`, `installer/install.bat`, `pyproject.toml`
- Exclusions / limits: 未实际触发 release

| Subtype | Count | Affected Surface | Recommended Action |
|---------|-------|------------------|-------------------|
| Workflow correctness | 2 | `release.yml`, `docker-release.yml` 指向 crawl4ai | 改为 thunder-capture |
| CI secrets | 1 | fallback secret | 删除 fallback |
| Reproducibility | 2 | unpinned base images, no lockfile in Docker | digest pin + uv.lock |
| Versioning / docs | 2 | version duplicated, no CHANGELOG | 从 pyproject.toml 读取、生成 CHANGELOG |
| Installer | 1 | install.bat 不迁移 DB | 加 alembic upgrade、校验 secret |

### 5.8 Supply Chain / Reproducibility Analysis

- Coverage: High
- Inspected evidence: `pyproject.toml`, `requirements/*.txt`, `deps/*/LICENSE`, `deps/*/pyproject.toml`, `scripts/gen-sbom.sh`, workflows
- Exclusions / limits: 未扫描全部 transitive deps

| Subtype | Count | Affected Surface | Recommended Action |
|---------|-------|------------------|-------------------|
| License compliance | 2 | MediaCrawler NC license, MIT/Apache conflict | 替换/获得授权/拆插件；统一声明 |
| Dependency pinning | 2 | pyproject >= ranges, requirements 重复 | uv.lock 为唯一真相源 |
| Vendored conflicts | 1 | MediaCrawler/crawl4ai 与主项目版本冲突 | workspace 统一 lock 或移除 vendoring |
| SBOM / CI | 1 | `gen-sbom.sh` 未在 CI 运行 | 自动生成为 release artifact |

### 5.9 Cost / Resource Economics Analysis

- Coverage: High
- Inspected evidence: LLM call sites, vision screenshots, retry logic
- Exclusions / limits: 未连接真实账单

| Subtype | Count | Cost Driver | Recommended Action |
|---------|-------|-------------|-------------------|
| Cost visibility | 1 | 无 token/usage 记录 | 每次 LLM 调用记录 usage |
| LLMCost | 2 | full base64 screenshots, no budget caps | 压缩截图、per-industry/user 预算 |
| ExternalApiCost | 1 | DirectLLM 无 retry 导致重复采集 | 加 retry/backoff |

### 5.10 AI / LLM Safety Analysis

- Coverage: High
- Inspected evidence: `core/classify.py`, `core/task/worker.py`, `core/agent/direct_glm.py`, `core/agent/executor.py`, `core/agent/planner.py`, `server/services/llm.py`
- Exclusions / limits: 未做完整 red-team

| Subtype | Count | Boundary Crossed | Recommended Action |
|---------|-------|------------------|-------------------|
| PromptInjection | 2 | Comments/seed_keyword in classification & reply prompts | 隔离 system/user 内容、加界定、注入检测 |
| OutputValidation | 1 | Replies sent without content filter | 内容审核层 |
| ToolAuthorization | 1 | Phone agent executes LLM ADB actions | 动作白名单、坐标校验、人工确认 |
| AbuseCost | 1 | No budget caps | per-user/per-industry token caps |

### 5.11 Observability / Operability Analysis

- Coverage: High
- Inspected evidence: `server/logging_config.py`, `server/middleware.py`, `server/api/stats.py`, `server/main.py`, `core/redis.py`, `server/services/webhook.py`
- Exclusions / limits: 未部署 Prometheus

| Subtype | Count | Critical Signals Missing | Recommended Action |
|---------|-------|--------------------------|-------------------|
| Metrics | 1 | 无 /metrics | prometheus-client |
| HealthCheck | 2 | health 需要 auth、未检查 Redis/Celery | 加 /healthz、ping Redis/Celery |
| Logging | 2 | 无 correlation ID、敏感信息未脱敏 | correlation middleware、redaction filter |
| Log level | 1 | 硬编码 INFO | `THUNDER_LOG_LEVEL` |

### 5.12 Configuration Safety Analysis

- Coverage: High
- Inspected evidence: `.env`, `config/system.yaml`, `server/config.py`, `core/config.py`, `adapters/dify/client.py`, `start_system.bat`
- Exclusions / limits: 未检查所有行业模板

| Subtype | Count | Affected Keys / Files | Recommended Action |
|---------|-------|-----------------------|-------------------|
| SecretConfig | 1 | `.env` 在根目录 | 删除、轮换、用 secret manager |
| SchemaValidation | 2 | `system.yaml`, env vars, Dify settings | Pydantic BaseSettings + model |
| UnsafeDefault | 1 | `start_system.bat` 回退到 SQLite | 移除回退或显式 flag |
| EnvironmentSeparation | 1 | 仅 secret/CORS 按环境区分 | 环境特定 profile |

### 5.13 Data Integrity Analysis

- Coverage: High
- Inspected evidence: Models, migrations, scheduler, API transaction boundaries
- Exclusions / limits: 未做 chaos/fault injection

| Subtype | Count | Invariants at Risk | Recommended Action |
|---------|-------|-------------------|-------------------|
| ConcurrencyConsistency | 4 | send job start, device limits, quota reservation, task claim | 唯一索引 / SELECT FOR UPDATE / 原子 UPDATE |
| TransactionBoundary | 3 | device scan, industry delete, quota+claim | 单事务 |
| MigrationSafety | 2 | dual migration systems, additive migrations | 统一 Alembic |
| Idempotency | 1 | webhooks 无幂等键 | Idempotency-Key + 投递日志 |
| InvariantValidation | 1 | retry_after string compare | DateTime 列 |

### 5.14 Backend API Analysis

- Coverage: High
- Inspected evidence: All `server/api/*.py`, schemas, services
- Exclusions / limits: 未做 fuzz/pen-test

| Subtype | Count | Affected Endpoints | Recommended Action |
|---------|-------|-------------------|-------------------|
| BusinessLogic | 3 | send job start, GET reconciliation, lead export | 原子化、移到后台、白名单 |
| NplusOne | 2 | dashboard, jobs list | 窗口函数批量取 |
| ErrorResponse | 2 | HTTPException vs AppError, leads silent error | 统一信封、真实报错 |
| Validation | 1 | retry_after string compare | DateTime |
| Pagination | 1 | jobs normalized status | 下推分页 |

### 5.15 Type Safety Analysis

- Coverage: Medium
- Inspected evidence: `mypy` output, `pyproject.toml` overrides
- Exclusions / limits: 未修复所有错误

| Subtype | Count | Critical | High | Medium | Low |
|---------|-------|----------|------|--------|-----|
| UnsafeBlock | 0 | 0 | 0 | 0 | 0 |
| TypeAssertion | 0 | 0 | 0 | 0 | 0 |
| InputBoundary | 0 | 0 | 0 | 0 | 0 |
| OutputLeak | 0 | 0 | 0 | 0 | 0 |
| BooleanTrap | 0 | 0 | 0 | 0 | 0 |
| StringlyTyped | 1 | 0 | 0 | 1 | 0 |
| ErrorType | 1 | 0 | 1 | 0 | 0 |

- **ErrorType (High)**: 16 个关键模块被 `ignore_errors = true`  blanket 忽略。
- **StringlyTyped (Medium)**: `TaskQueue.retry_after` 使用字符串比较时间。

### 5.16 Frontend State Analysis

- Coverage: Not assessed
- Inspected evidence: `server/static/index.html` 与少量 Vanilla JS
- Exclusions / limits: 项目以后端/CLI 为主；本次审计未将前端状态管理作为重点。如需可单独审计 `server/static/`。

---

## 6. Principles Compliance

### Principles Violated

| Principle | Violations | Severity | Affected Areas |
|-----------|------------|----------|----------------|
| Single Responsibility (SRP) | 4 | High | `server/api/industries.py` (1360 行), `server/workers.py` (1035 行), `core/task/runner.py` 的 `run_douyin_dm` (299 行), `core/agent/direct_glm.py` 的 `execute_plan` (188 行) |
| File Size Limit | 3 | Medium | `server/api/industries.py`, `server/workers.py`, `server/services/task_stats.py` |
| Fail-Fast | 5 | High | 配置无 schema 校验、大量 `except Exception: pass`、leads endpoint 吞错误、Dify/classify 静默失败 |
| Immutability / No Hidden Side Effects | 3 | High | GET endpoints 修改 job 状态、全局 client/router 无锁可变、in-memory job cache 不共享 |
| Layered Architecture / Dependency Direction | 1 | High | `core` 导入 `server`/`adapters`，`server` 导入 `scripts.smoke` |
| Defense in Depth | 4 | High | prompt 直接拼接、LLM 动作无白名单、webhook 无签名、速率限制信任 XFF |

### Principles Respected

- **Explicit error handling in some paths**: `server/main.py` 统一 `AppError` 异常 handler，部分 API 使用 Pydantic 校验。
- **Dependency injection for DB sessions**: `get_db` + FastAPI `Depends` 在多数路由中使用。
- **No raw SQL concatenation**: 全部使用 SQLAlchemy ORM，降低注入风险。
- **Password hashing with bcrypt**: `server/auth.py` 使用 `bcrypt` 并正确加盐。
- **Test suite exists and passes**: 381 个测试在正确命令下通过，说明核心流程有基本保护。

---

## 7. Architecture Analysis

### Architecture Summary

| Subtype | Count | Affected Areas | Recommended Action |
|---------|-------|----------------|-------------------|
| ModuleBoundary | 3 | `core` 依赖 `server`/`adapters`；`server` 依赖 `scripts.smoke`；`adapters/celery` 依赖 `server.api` | 提取 `models/` 公共包；celery 任务只依赖 services/models；server 不依赖 scripts |
| DependencyDirection | 2 | `core -> server`, `core -> adapters` | 反转依赖：core 定义 port，adapter 实现 |
| StateOwnership | 2 | in-memory `_jobs` / `_reply_client` / `_router` 状态不跨进程共享 | 使用 Redis / per-instance 初始化 |
| BoundaryContract | 2 | Celery 任务参数缺少 `user_id`；LLM prompts 无 schema | 任务签名加 `user_id`；prompt 加输出 schema |
| EvolutionRisk | 2 | vendored deps 与主项目版本冲突；双轨迁移 | 统一 lockfile / Alembic |

### Key Detail

**Cross-layer imports violate documented architecture.** `PROJECT_STRUCTURE.md` 声称 `core/` 不依赖外部基础设施，但 `core/classify.py` 导入 `server.services.task_stats`，`core/discover.py` 导入 `adapters.mediacrawler.runner`，`core/config.py` 导入 `server.models` 与 `server.secret_store`。结果是 `core` 无法在不启动 SQLAlchemy/secret 的情况下单元测试，任何 `server` 的重构都会波及业务核心。建议将 `server.models` 提升为顶层 `models/` 包，`core` 通过函数参数或协议接收所需服务，彻底切断 `core -> server/adapters` 的边。

---

## 8. Documentation Analysis

### Documentation Summary

| Subtype | Count | Affected Docs | Recommended Action |
|---------|-------|---------------|-------------------|
| UserDocs | 1 | `README.md` 路径错误 | 更新为 `requirements/base.txt` / `deps/Open-AutoGLM` |
| OperatorDocs | 2 | 无生产部署 runbook；docker-compose healthcheck 与 auth 冲突 | 补充部署/回滚/告警 runbook；修复 healthcheck |
| DeveloperDocs | 2 | `PROJECT_STRUCTURE.md` 与实际依赖不符；大量公共函数无 docstring | 更新文档或重构；补 docstring |
| ApiDocs | 1 | 错误响应结构不统一 | 统一错误 envelope 并文档化 |
| StaleDocs | 1 | `README.md` 中的 requirements 路径 | 同上 |

---

## 9. Privacy / Data Governance Analysis

### Privacy Summary

| Subtype | Count | Affected Data | Recommended Action |
|---------|-------|---------------|-------------------|
| DataInventory | 1 | Lead 导出可导出内部列 | 字段白名单 |
| AccessBoundary | 2 | 跨租户 slug 导致数据访问错乱；无主 TaskQueue 可被任意 scheduler 申领 | 租户隔离；owner non-nullable |
| TelemetryPrivacy | 2 | 日志打印 Redis URL / webhook URL / proxy 凭据 | 日志脱敏 |
| Retention | 0 | — | 建议增加数据保留/删除策略 |
| Deletion | 1 | 删除 industry 时按 slug 跨租户清理 | 按 owner 过滤 |
| Export | 1 | lead export 字段无限制 | 白名单 |

---

## 10. Supply Chain / Reproducibility Analysis

见 5.8。

---

## 11. Cost / Resource Economics Analysis

见 5.9。

---

## 12. AI / LLM Safety Analysis

见 5.10。

---

## 13. Observability / Operability Analysis

见 5.11。

---

## 14. Configuration Safety Analysis

见 5.12。

---

## 15. Data Integrity Analysis

见 5.13。

---


### 5.17 Accessibility / UX Correctness Analysis

- Coverage: Not assessed
- Inspected evidence: `server/static/index.html` 与少量 Vanilla JS SPA
- Exclusions / limits: 项目以后端/CLI 为主，前端界面未作为本次审计重点

| Subtype | Count | Affected Workflows | Recommended Action |
|---------|-------|-------------------|-------------------|
| SemanticStructure | 0 | — | 如需可单独审计 `server/static/` |
| KeyboardFocus | 0 | — | 同上 |
| ResponsiveVisual | 0 | — | 同上 |
| ErrorState | 0 | — | 同上 |
| LoadingState | 0 | — | 同上 |
| UXStateCorrectness | 0 | — | 同上 |

### 5.18 Fallback / Defensive Code Analysis

- Coverage: High
- Inspected evidence: `core/classify.py`, `adapters/dify/client.py`, `server/services/task_stats.py`, `core/device/supervisor.py`, `server/api/leads.py`, `adapters/mediacrawler/runner.py`
- Exclusions / limits: 未做静态全量扫描

| Subtype | Count | KeepWithAlert | FailFast | Remove |
|---------|-------|---------------|----------|--------|
| SilentFallback | 6 | 0 | 6 | 0 |
| EmptyCatch | 4 | 0 | 4 | 0 |
| CompatibilityBranch | 0 | 0 | 0 | 0 |
| SilentCorrection | 1 | 0 | 1 | 0 |
| DefensiveGuess | 1 | 0 | 1 | 0 |

主要问题：大量 `except Exception: pass/log` 将真实错误伪装成正常路径，应改为区分错误类型、记录并上报。

### 5.19 Testing Authenticity Analysis

- Coverage: High
- Inspected evidence: `tests/`, 381 passing tests, ruff/mypy output
- Exclusions / limits: 未逐行阅读全部测试

| Test Area | Real Confidence | Risk | Action |
|-----------|---------------|------|--------|
| API contract tests | Medium | 部分测试直接测私有函数 | 优先通过公共端点测试 |
| Worker tests | Low | 使用 time.sleep 等待后台线程 | 改为事件同步 |
| Unit tests | Medium | 共享持久数据库 | 改为 per-test in-memory DB |
| E2E / real_device | Low | 未正确标记，默认运行 | 加 skipif 与 markers |

### 5.20 Dependency Weight Analysis

- Coverage: Medium
- Inspected evidence: `pyproject.toml`, `requirements/*.txt`, vendored `deps/`, `uv.lock`
- Exclusions / limits: 未精确测量每个依赖体积

| Dependency | Status | Weight | Transitives | Used For | Recommended Action |
|------------|--------|--------|-------------|----------|-------------------|
| MediaCrawler (vendored) | Dead/Legal risk | 高 | 多 | 抖音采集 | 替换或拆插件 |
| Open-AutoGLM (vendored) | Overweight | 高 | 多 | 手机自动化 | 评估是否可依赖发布包 |
| crawl4ai (vendored) | Overweight | 中 | 多 | 网页抓取 | 同上 |
| easyocr | Healthy | 中 | 多 | OCR | 保留 |
| playwright | Healthy | 高 | 多 | 浏览器 | 保留 |

### 5.21 Code Consistency Analysis

- Coverage: Medium
- Inspected evidence: ruff check/format output, import style, naming conventions
- Exclusions / limits: 未配置自定义 ruff 规则

| Subtype | Count | Affected Components |
|---------|-------|-------------------|
| ImportStyle | 1 | 未配置 ruff isort |
| Naming | 0 | 基本遵循 snake_case |
| Formatting | 1 | 117 文件需 reformat |
| LinterRules | 1 | `[tool.ruff]` 缺失 |

### 5.22 Comment Coverage Analysis

- Coverage: Low
- Inspected evidence: 公共函数抽样
- Exclusions / limits: 未使用工具统计

| Subtype | Count | Affected Files |
|---------|-------|----------------|
| MissingDocstring | 231 | `core/`, `server/`, `adapters/`, `cli.py` |
| StaleComment | 0 | — |
| MisleadingComment | 0 | — |


## 16. Recommended Fix Order

### Fix Immediately

1. **删除项目根 `.env` 并轮换所有密钥**（Finding 1）
2. **修复跨租户 slug 唯一约束并让所有查询带 user_id**（Finding 2）
3. **评估 MediaCrawler 许可证风险并替换/获得授权**（Finding 3）
4. **修复 release workflow 指向错误项目**（Finding 4）
5. **为 LLM 回复增加内容安全过滤**（Finding 5）
6. **限制 Phone Agent 可执行动作并加白名单**（Finding 6）
7. **增加 LLM token/成本追踪与预算上限**（Finding 7）
8. **统一迁移系统到 Alembic**（Finding 8）

### Fix Before Stable Release

9. 修复发送任务启动竞态（Finding 22）
10. 修复设备并发限额（Finding 23）
11. 修复 Jobs list 未分页问题（Finding 24）
12. 添加 FastAPI lifespan/shutdown hook（Finding 25）
13. 修复 Celery 任务重试不触发（Finding 26）
14. Webhook 加签名/重试/幂等键（Finding 27）
15. 修复全局 client/router 线程安全（Finding 28、29）
16. 修复 asyncio.run 在 Celery 中的问题（Finding 30）
17. 修复分类/Dify/入队静默失败（Finding 31、32、33）
18. 修复 health endpoint 认证与 compose healthcheck（Finding 34）
19. 配置 schema 校验（Finding 35）
20. 修复架构跨层依赖（Finding 36）
21. 拆分超大文件/函数（Finding 37）
22. 移除 mypy blanket ignore（Finding 38）

### Schedule Later

23. 拆分 vendored deps 或统一 lockfile（Finding 11、13）
24. 解决许可证声明冲突（Finding 12）
25. 添加 Prometheus 指标与告警（Finding 53）
26. 添加 correlation ID 与结构化日志（Finding 54）
27. 压缩/缓存 DirectGLM 截图（Finding 51）
28. N+1 查询优化（Finding 46、47）
29. 补 docstring 与文档（Finding 55、56、86）
30. 测试覆盖率门与隔离（Finding 39、40、41）

### Ignore for Now

- 低优先级：CSP/HSTS 缺失（虽然建议加，但需配合反向代理）
- 公式注入风险（Low/Suspected，导出场景相对受限）
- acceptance evidence 所有权校验缺口（Low/Suspected，UUID 猜测难度高）

## 17. Quick Wins

| Fix | Effort | Finds Addressed |
|-----|--------|-----------------|
| 添加 `testpaths` 与 `norecursedirs` | XS | Finding 39 |
| 删除 CI fallback secret | XS | Finding 10 |
| 更新 README 路径 | XS | Finding 55 |
| 修复 docker-compose healthcheck | XS | Finding 34 |
| 移除 device scan / industry delete 的多余 commit | XS | Finding 43、44 |
| 修复 leads endpoint 吞错误 | XS | Finding 48 |
| 修复 LLM client cache key | S | Finding 15 |
| 修复 retry_after 字符串比较 | S | Finding 45 |
| 修复 webhook 重定向校验 | S | Finding 20 |
| 修复 rate limiter XFF 信任 | S | Finding 21 |

## 18. Long-term Refactor Plan

### 1. 租户隔离重构
- **Motivation**: 当前 `industry_slug` 与无主 `TaskQueue` 导致多租户数据错乱，是 SaaS 化的最大 blocker。
- **Approach**: 为 `Industry`、`TaskQueue`、`TargetBlogger`、`CollectedVideo`、`IndustryDailyQuota` 增加 `user_id` 并建唯一约束；Celery 任务签名加 `user_id`；所有按 slug 查询改按 `(user_id, slug)`。
- **Risk**: 需要数据迁移与回填；测试需覆盖跨租户场景。
- **Testing**: 新增 contract tests 验证两个同名 slug 用户的数据隔离。

### 2. 架构分层清理
- **Motivation**: `core` 不应依赖 `server`/`adapters`。
- **Approach**: 提取 `models/` 与 `ports/` 包；`core` 只依赖 `ports` 与 `models`；`adapters` 实现 port；`server` 编排。
- **Risk**: 改动面大，需分阶段进行。
- **Testing**: 静态 import graph 检查 + 单元测试不依赖 SQLAlchemy。

### 3. LLM 安全与成本治理
- **Motivation**: prompt injection、内容安全、成本失控是上线后的核心风险。
- **Approach**: 统一 LLM client 封装，内置 token 记录、预算检查、prompt 隔离、输出 schema 校验、内容审核 callback。
- **Risk**: 增加延迟；需维护审核规则。
- **Testing**: 红队测试集覆盖 injection、越狱、毒性输出。

### 4. 可观测性体系
- **Motivation**: 当前无指标、日志无 correlation、health 不完整。
- **Approach**: 加 `/metrics`、correlation middleware、结构化 JSON 日志、Redis/Celery 健康检查、关键路径 histogram。
- **Risk**: 增加少量开销。
- **Testing**: 部署后验证 Grafana/告警能正常工作。

### 5. 发布与供应链硬化
- **Motivation**: release 流程错误、依赖未 pin、许可证冲突。
- **Approach**: 修正 workflow；使用 `uv.lock`；CI 生成 SBOM 与 license report；移除或替换 MediaCrawler。
- **Risk**: MediaCrawler 替换成本高。
- **Testing**:  staging release + license scan。

---

*Report generated by fuck-my-shit-mountain skill. AI audit is review assistance, not a replacement for human review, security testing, and production monitoring.*
