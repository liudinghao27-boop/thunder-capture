# Thunder Capture 代码审计报告

**审计日期：** 2026-06-16  
**审计范围：** `server/`、`core/`、`adapters/`、`cli.py`、`server/static/index.html`  
**审计分支：** `feat/phase1-export-compliance-new`  
**审计提交：** `42b1417`  
**审计方法：** 自动化工具（pytest / ruff / mypy / alembic）+ 人工代码审查 + 子代理专项审计

---

## 1. 执行摘要

本次审计共发现 **51+ 项问题**，覆盖安全漏洞、逻辑错误、性能瓶颈和代码质量四类。其中：

| 类别 | 严重 | 高 | 中 | 低 | 小计 |
|---|---:|---:|---:|---:|---:|
| 安全 | 1 | 3 | 4 | 2 | 10 |
| 逻辑 | 0 | 12 | 9 | 3 | 24 |
| 性能 | 4 | 0 | 9 | 4 | 17 |
| 质量 | - | - | - | - | 多项 |

**本次已修复 30 项核心问题**（含后续补修的 5 项 High 风险），剩余问题已记录并给出修复建议。修复后全量测试 **199 passed, 1 warning**，Alembic 迁移同步，但仍存在约 47 条 ruff 警告和 345 条 mypy 类型错误（多数为历史遗留或 SQLAlchemy 类型推断问题）。

---

## 2. 审计方法

1. **基线验证**
   - `python -m pytest tests/ -q`
   - `python -m ruff check server/ core/ tests/ adapters/ cli.py`
   - `python -m mypy server/ core/ adapters/ cli.py --ignore-missing-imports`
   - `alembic upgrade head && alembic check`

2. **专项子代理审计**
   - 安全审计：授权绕过、SSRF、注入、CORS、密钥管理
   - 性能审计：N+1 查询、全表扫描、同步 I/O、缺失索引
   - 逻辑/质量审计：状态机、字段映射、Celery、CLI、ORM 使用

3. **根因确认**
   - 对每个高优先级问题，通过读取源码、模型定义和调用链确认根因
   - 通过 TDD 编写失败用例 -> 修复 -> 验证的流程实施修复

---

## 3. 已修复问题清单

### 3.1 安全漏洞（Critical / High / Medium）

| # | 问题 | 严重级别 | 修复文件 | 修复说明 |
|---|------|---------|---------|---------|
| 1 | Leads API 跨租户访问：`list_leads`、`lead_stats`、`retry_failed_leads` 未按 `owner_user_id` 过滤 | Critical | `server/api/leads.py` | 新增 `_owner_filter()`，所有查询加入当前用户隔离 |
| 2 | Stats/Dashboard funnel 跨租户：`queue_stats`、`funnel_stats` 等未按用户过滤 | High | `server/services/task_stats.py`、`server/api/dashboard.py` | 为统计函数增加 `owner_user_id` 参数并下传 |
| 3 | Webhook SSRF：`webhook_url` 仅校验 `^https?://\S+$`，可指向内网/元数据服务 | High | `server/schemas/industry.py`、`server/services/url_security.py`、`server/api/industries.py`、`server/services/webhook.py`、`server/services/effect_webhook.py` | 新增 `is_safe_webhook_url()`：强制 HTTPS、阻断私网/回环/链路本地/多播地址、DNS 解析二次校验；测试 webhook 不再返回原始响应体 |
| 4 | Lead export HTTP 响应头拆分：`industry_slug` 直接拼入 `Content-Disposition` | High | `server/api/leads.py` | 增加 slug 正则校验，文件名使用 `urllib.parse.quote` |
| 5 | 用户设置更新使用 `"****" not in key` 子串判断，存在误更新和批量赋值风险 | Medium | `server/api/auth.py` | `None` = 不更新，`""` = 清空，非空 = 加密保存 |
| 6 | Dashboard failure distribution 未按用户过滤 | Medium | `server/api/dashboard.py` | 查询加入 `owner_user_id` 过滤 |

### 3.2 逻辑错误（High）

| # | 问题 | 修复文件 | 修复说明 |
|---|------|---------|---------|
| 7 | 全局日配额 `reserved` 永远不释放，达到上限后永久无法发送 | `core/task/scheduler.py` | `mark_task_done()` 成功后调用 `self.commit()`；失败/重试/释放时调用 `self.release()` |
| 8 | `daily_send_max` 未预留和下发，并发会超发 | `core/task/scheduler.py`、`core/task/worker.py` | 预留逻辑与 `global_daily_limit` 统一；`DeviceWorker` 传入 `daily_send_max` |
| 9 | Worker 读取错误 task key：`source_short_id` / `source_sec_uid` 不存在 | `core/task/worker.py` | 改为读取 `short_id` / `douyin_id` / `unique_id` / `user_id` / `sec_uid` |
| 10 | LLM 返回 `None` content 时崩溃 | `core/task/worker.py` | 对 `message.content` 做空值保护 |
| 11 | `matched_categories` 双重 JSON 编码 | `core/classify.py` | `enqueue_classified()` 区分字符串与 dict，避免重复 `json.dumps` |
| 12 | `server/services/task_stats.py` 引用不存在的列 | `server/services/task_stats.py` | `aweme_id`、`value`、`discovered_at` 等字段对齐模型 |
| 13 | Celery classify 调用不存在的 `classify_batch()` 并缺少 IndustryConfig 必填字段 | `adapters/celery/classify.py` | 改为 `client.classify()` 并补全 `reply_tone` / `reply_style` / `reply_hook` |
| 14 | Celery send task 全局 `rate_limit="15/h"` 导致多设备总吞吐崩溃 | `adapters/celery/send.py` | 移除全局 rate limit，说明由 `DeviceWorker.min_interval` 控制 |
| 15 | Celery collect task 为 no-op stub | `adapters/celery/collect.py` | 调用 `adapters.mediacrawler.runner.run_platform` 并返回真实结果 |
| 16 | `generate-config-bigdata` 导入不存在的 `core.collectors.douyin` | `server/api/industries.py` | 返回 HTTP 501 并给出明确错误信息 |
| 17 | CLI 引用未定义函数 / 参数顺序错误 | `cli.py`、`server/services/task_stats.py` | 移除 `reclaim_stale_claims`；`add_blogger` 补 `short_id=""`；`set_blogger_status` 替换为 `mark_target_inactive` |
| 18 | `mark_lead_replied` / `unmark_lead_converted` 使用非法状态 `"sent"` | `server/api/leads.py` | 统一使用 `"done"` 作为已发送基态 |
| 19 | 设备重复调度：`MatrixDevice.is_available()` 对 `"running"` 返回 True | `core/device/manager.py` | 将 `"running"` 加入不可用状态集合 |
| 20 | `core/discover.py` 与 `server/workers.py` 数据契约不一致 | `core/discover.py`、`server/workers.py` | `run_discovery()` 统一返回候选评论列表，由调用方负责分类入队 |
| 21 | `server/services/analytics.py` 全量加载后 Python 过滤日期 | `server/services/analytics.py` | `query_task_rows()` 在 SQL 层按 `fetched_at >= since` 过滤 |
| 22 | `server/services/task_stats.py` 多个统计函数全表加载 + Python 聚合 | `server/services/task_stats.py` | `keyword_funnel_stats`、`source_type_funnel_stats`、`source_performance_stats`、`blogger_source_stats` 改为 SQL `GROUP BY` 聚合 |
| 23 | `core/classify.py` 逐条入队，每条一次 Session/查询 | `core/classify.py`、`server/services/task_stats.py` | 新增 `enqueue_tasks_batch()`，使用方言特定的 `INSERT ... ON CONFLICT DO NOTHING` 批量入队 |
| 24 | 异步路径中同步 I/O 阻塞事件循环 | `server/api/devices.py` | 对 ADB 健康检查、键盘准备、屏幕控制等同步调用包裹 `asyncio.to_thread()` |

### 3.3 性能与质量（Medium / Low）

| # | 问题 | 修复文件 | 修复说明 |
|---|------|---------|---------|
| 19 | `InMemoryRateLimiter` 使用 `list.pop(0)` 导致 O(n) | `server/middleware.py` | 改用 `collections.deque` |
| 20 | `TaskQueue` 缺少复合索引，claim/stats 查询易全表扫描 | `server/models/task.py` | 新增 `(industry_slug, status)`、`(industry_slug, status, owner_user_id)`、`(fetched_at)` 索引 |
| 21 | `system_health` 遮蔽注入的 `db` 变量 | `server/api/stats.py` | 局部变量重命名为 `health_db` |
| 22 | 多处未使用 import | `core/agent/direct_glm.py`、`core/discover.py`、`core/robotstxt.py`、`core/strategy/risk.py`、`adapters/postgres/migrations/env.py` | ruff 自动清理 |

---

## 4. 验证结果

### 4.1 测试

```bash
python -m pytest tests/ -q --tb=short
```

**结果：199 passed, 1 warning**

新增/更新测试覆盖：
- `tests/server/api/test_leads.py` / `test_leads_tenant.py`
- `tests/server/api/test_auth.py`
- `tests/server/api/test_dashboard.py`
- `tests/server/services/test_url_security.py`
- `tests/server/services/test_effect_webhook.py`
- `tests/server/services/test_task_stats.py`
- `tests/core/task/test_scheduler.py`
- `tests/core/task/test_worker_abtest.py`
- `tests/core/task/test_worker_compliance.py`
- `tests/core/test_classify.py`
- `tests/adapters/celery/test_classify.py`
- `tests/adapters/celery/test_collect.py`
- `tests/test_cli.py`
- `tests/server/test_middleware.py`
- `tests/server/test_task_queue_indexes.py`
- `tests/server/api/test_industries_bigdata.py`

### 4.2 Alembic

```bash
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic upgrade head
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic check
```

**结果：`No new upgrade operations detected.`**

新增迁移：
- `adapters/postgres/migrations/versions/81fe0505b506_add_task_queue_composite_indexes.py`

### 4.3 静态检查

| 工具 | 结果 | 备注 |
|------|------|------|
| ruff | 47 errors remaining | 多为历史遗留（`E402 import not at top`、`E712 == True`、`F401 unused import`） |
| mypy | 345 errors | 多为 SQLAlchemy `Column[str]` 类型推断、已有 Pydantic/字典类型问题；mypy 2.1.0 在 Python 3.14 下偶发内部错误 |

**说明：** 剩余 lint/type 错误未在本次全部修复，避免单次改动过大。建议作为持续重构项分批处理。

---

## 5. 未修复问题与建议

以下问题在本次审计中被识别，但因改动范围大或优先级较低，未在本次修复。建议后续按优先级处理。

### 5.1 安全（剩余）

| # | 问题 | 严重级别 | 建议 |
|---|------|---------|------|
| 1 | `scripts/smoke/reset_admin.py` 硬编码管理员密码 | Medium | 从仓库移除或改为从环境变量读取强密码 |
| 2 | CORS 默认允许 `localhost:5173/3000` 且 `allow_credentials=True` | Medium | 生产环境默认空列表，未配置时拒绝启动 |
| 3 | JWT 开发密钥自动生成并持久化到 `data/.thunder_secret_key` | Medium | 生产环境强制 `THUNDER_SECRET_KEY`，密钥存密钥管理器 |
| 4 | `scripts/reset_db.py` 使用 f-string 拼接表名 | Low | 使用 SQLAlchemy Core `table.delete()` |
| 5 | `escapeHtml()` 未转义反斜杠，属性场景有隐患 | Low | 增加 `\\` 转义 |

### 5.2 逻辑（剩余）

| # | 问题 | 严重级别 | 建议 |
|---|------|---------|------|
| 1 | `core/browser_orchestrator.py` 仅支持 Windows | Medium | 增加 Linux/macOS Chrome 路径和进程管理 |
| 2 | `core/discover.py` 与 `adapters/mediacrawler/runner.py` 重写依赖配置文件，并发冲突 | Medium | 使用环境变量或临时目录隔离配置 |
| 3 | `is_send_window_open()` 使用 UTC 与本地时间比较 | Medium | 转换到配置时区再比较 |
| 4 | ADB text input 存在 shell 注入 | Medium | 使用 ADB Keyboard 广播路径，或对 fallback 做 shell 转义 |
| 5 | `ProxyRotator` 直接保存外部列表引用 | Low | `self._proxies = list(proxies)` |
| 6 | `server/services/migrations.py` 缺失部分 Industry 列 | Low | 补全 `ADDITIVE_MIGRATIONS` |

### 5.3 性能（剩余）

| # | 问题 | 严重级别 | 建议 |
|---|------|---------|------|
| 1 | `server/api/dashboard.py` execution monitor N+1 | Medium | 使用 `LATERAL` 或窗口函数取最新记录 |
| 2 | LLM 调用在 FastAPI async 路由中同步阻塞 | Medium | 使用 `openai.AsyncOpenAI` 或 `asyncio.to_thread()` |
| 3 | `load_system()` 每次调用重新解析 YAML | Medium | `functools.lru_cache` 缓存 |
| 4 | 多处列表端点无分页 | Medium | 增加默认 limit / cursor 分页 |
| 5 | Lead export 一次性构建完整 XLSX | Medium | CSV 流式输出；XLSX 使用 openpyxl 常量内存模式 |
| 6 | `claim_token` LIKE 查询无索引 | Medium | 使用 `job_id` 索引替代 |
| 7 | 每条私信单独 LLM 调用 | Low | 增加 `(variant_id, comment_hash)` 回复缓存 |
| 8 | MJPEG 每帧重新 resize | Low | 降低 FPS / 复用缓冲区 |

---

## 6. 审计报告使用指导

### 6.1 如何复现本次审计

```bash
# 1. 进入项目目录
cd C:/Users/Administrator/Desktop/shemeihuoke

# 2. 激活虚拟环境（已安装 dev 依赖）
source .venv/Scripts/activate

# 3. 运行全量测试
python -m pytest tests/ -q --tb=short

# 4. 运行 lint
python -m ruff check server/ core/ tests/ adapters/ cli.py

# 5. 运行类型检查
python -m mypy server/ core/ adapters/ cli.py --ignore-missing-imports

# 6. 验证数据库迁移
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic upgrade head
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic check
rm -f data/thunder.db data/thunder.db-*
```

### 6.2 如何继续修复剩余问题

1. **按优先级排序**：建议先处理所有 High/Critical 安全与逻辑问题，再处理性能问题。
2. **使用 TDD**：对每个问题先写失败测试，再修复，最后验证。
3. **小步提交**：每个问题或每组相关问题单独 commit，便于回滚和 review。
4. **参考本报告**：第 5 节中的每项都给出了具体修复建议，可直接转化为任务。
5. **静态检查清理**：建议每周花 1-2 小时处理一批 ruff/mypy 警告，直至清零。

### 6.3 推荐后续任务清单

- [x] 修复设备重复调度问题（`MatrixDevice.is_available()` + 调度锁）
- [x] 统一 `core/discover.py` 与 `server/workers.py` 的数据契约
- [x] 将 analytics / funnel stats 改为 SQL 聚合
- [x] 批量入队 classified comments
- [x] 为异步路径中的同步 I/O 添加 `asyncio.to_thread()`
- [ ] 移除或加固 `scripts/smoke/reset_admin.py`
- [ ] 生产环境强制 `THUNDER_SECRET_KEY` 和严格 CORS
- [ ] 清理剩余 ruff 47 errors 和 mypy 345 errors

---

## 7. 结论

本次审计修复了最严重的安全漏洞、逻辑错误和性能瓶颈，全量测试通过，数据库迁移同步。后续补修的 5 项 High 风险（设备调度、数据契约、SQL 聚合、批量入队、异步 I/O）也已全部完成。系统在当前分支上比之前更健壮、更安全、更可扩展。剩余问题主要为跨平台兼容性、历史 lint/type 技术债和若干 Medium/Low 优化项，建议按优先级分批处理。

**审计完成提交：** `42b1417`  
**后续 High 风险修复提交：** 见当前分支最新提交（`feat/phase1-export-compliance-new`）  
**报告作者：** Kimi Code CLI  
**报告路径：** `docs/superpowers/audits/2026-06-16-code-audit-report.md`
