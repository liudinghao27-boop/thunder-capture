# 雷霆捕获系统 Phase 9 Commit & Merge Review

> **文档版本**：v1.0  
> **创建日期**：2026-07-09  
> **审查基线**：`3288d04b0f4f0dd23484b00a2f1f98d01987673a` + Phases 4–6 变更  
> **审查方式**：子代理分区域审查 + 手动热点复核

---

## 1. 审查结论

**总体 verdict：CONDITIONAL APPROVE（带条件通过）**

Phases 4–6 的脚手架、租户隔离与 TDD 修复整体正确，质量门禁已恢复通过。本次审查发现 1 项 HIGH 正确性问题已当场修复，另有 **3 项 HIGH 遗留问题** 和若干 MEDIUM/LOW 建议，需要在 Phase 10 或下一阶段优先处理。

---

## 2. 本次已修复问题

| 问题 | 位置 | 修复内容 | 验证 |
|------|------|----------|------|
| `make health` 端点错误 | `Makefile:59` | `/api/system/health` → `/api/system/live` | 手动检查 |
| 配额释放缺少租户过滤 | `core/task/scheduler.py:379` | `release()` 增加 `IndustryDailyQuota.owner_user_id == self.owner_user_id` | `tests/core/task/test_scheduler.py` 13 passed |
| runtime 文件被误跟踪 | `data/chrome_data/` | 已 `git rm -r --cached data/chrome_data`；`.gitignore` 已包含 | `git status` 中 `data/chrome_data/` 不再作为修改出现 |
| 新增 runtime 目录未忽略 | `.gitignore` | 增加 `data/chrome_cdp_profile/`、`data/chrome_data_backup*/`、`data/mc_failures/`、`scripts/data/` | `git status` 不再显示 |

---

## 3. 遗留 HIGH 问题（需在 Phase 10 或下阶段修复）

| 编号 | 问题 | 位置 | 风险 | 建议修复 |
|------|------|------|------|----------|
| HIGH-1 | `TaskQueue` 唯一约束未按租户拆分 | `server/models/task.py:105` | 不同租户收集同一评论/视频时，全局唯一约束会导致后入租户任务被当作重复丢弃 | 将 `UniqueConstraint("comment_id", "video_id", ...)` 改为 `("owner_user_id", "comment_id", "video_id")`，并同步改 `enqueue_tasks_batch_result` 的 `on_conflict_do_nothing(index_elements=...)` |
| HIGH-2 | `enqueue_task` 去重未按租户过滤 | `server/services/task_stats.py:863-871` | 租户 A 的 pending 任务会阻止租户 B 入队同一 source | 去重查询增加 `TaskQueue.owner_user_id == owner_user_id` |
| HIGH-3 | Celery 采集任务未透传 `user_id` | `adapters/celery/collect.py:38,48` | 采集入口仍按 `industry_slug` 触发，无用户上下文 | `run_full_collection` / `run_mediacrawler` 增加 `user_id` 参数并校验行业归属 |
| HIGH-4 | MediaCrawler cookie 路径硬编码 | `adapters/mediacrawler/runner.py:637` | 多租户共用 `data/douyin_cookies.json`，账号串号 | cookie 路径按 `user_id` 隔离，如 `data/cookies/{user_id}/douyin_cookies.json` |
| HIGH-5 | Celery 发送任务未校验设备归属 | `adapters/celery/send.py:33,95` | 任务 payload 被伪造时可能用他人设备发 DM | 在 `send_dm_task` 内查询 `Device.user_id == user_id`；长期用 `itsdangerous.TimestampSigner` 签名任务 |
| HIGH-6 | `core/discover.py` 无租户上下文 | `core/discover.py`（CLI/直接调用入口） | 可能写入 `owner_user_id = ""` 的数据 | 显式要求传入 `owner_user_id` 并断言非空 |

> 说明：HIGH-1/HIGH-2 互为表里，修复时需要一起改模型 + batch insert + 单条入队逻辑，并补一个 Alembic 迁移（删除旧唯一索引、创建租户级唯一索引）。

---

## 4. 其他观察（MEDIUM / LOW）

### 4.1 文件/函数规模

| 文件 | 行数 | 说明 |
|------|------|------|
| `server/api/industries.py` | 1,526 | 已超 800 行建议上限，但为既有文件；建议后续按 domain 拆分 |
| `server/services/task_stats.py` | 1,081 | 同上；聚合函数过多 |
| `server/workers.py` | 1,213 | 同上；含多个职责（job 生命周期、导出、 reconcile） |
| `core/task/scheduler.py` | ~567 | `claim_for_device()` ~106 行、`_ensure_quota_row()` ~59 行，建议后续拆分 |

### 4.2 可维护性

- `server/services/task_stats.py` 中 `_owner_filter()` 在 `owner_user_id` 为空时返回 `None`，相当于跳过租户过滤。API 层调用均传了 `current_user.id`，但内部函数若遗漏会造成隐式全局查询。建议将空字符串视为非法（断言/抛异常），或拆分出 `queue_stats_admin()` 等明确接口。
- `server/services/migrations.py` 回填使用 `MAX(...)` 推断唯一所有者，并跳过多所有者 slug/aweme_id，逻辑安全；但未匹配的遗留行 `owner_user_id` 为空，后续查询不会命中，数据会“孤儿化”。建议在运行一次后人工审计空值比例。
- `adapters/postgres/migrations/versions/*.py` diff 为纯格式化（black/ruff），无 schema 变更，安全但增加历史噪音。

### 4.3 安全/配置

- `docker-compose.yml` 健康检查已指向 `/api/system/live`，与代码一致。
- `.env.example` 无硬编码密钥，仅示例值。
- `server/api/system.py` 对数据库/Redis URL 做了脱敏处理。

---

## 5. 质量门禁复测

| 检查项 | 结果 |
|--------|------|
| ruff check | ✅ 0 errors |
| ruff format | ✅ OK（170 files） |
| pytest | ✅ **400 passed** |
| mypy | ⚠️ 12 pre-existing errors（未引入新错） |

---

## 6. Git 状态摘要

```text
- 修改/新增源文件：~120 个（Phases 4–6 的文档、API、服务、模型、core、adapters、tests、Makefile、docker-compose.yml 等）
- 删除跟踪：data/chrome_data/ 全部 runtime 文件（已 stage 为 D）
- 未跟踪待加入：docs/superpowers/specs/2026-07-09-saas-*.md、Makefile、server/api/system.py、tests/server/test_system.py、tests/server/test_industry_isolation.py 等
```

**建议提交拆分**（若用户决定提交）：

```
chore: untrack runtime chrome profile data
docs: add saas playbook specs for phases 1-8
feat: add /api/system/live info metrics endpoints and prometheus wiring
fix: tenant-scoped TaskQueue/TargetBlogger/CollectorState/IndustryDailyQuota
refactor: format and lint core/agent/strategy modules
feat: add Makefile and update docker-compose health checks
test: add system and tenant-isolation tests
```

或一次性 `feat(saasp): phases 4-6 scaffolding, tenant isolation and quality gate`（按团队习惯）。

---

## 7. 与 SaaS Dev Playbook 的对应

| Playbook Phase | 输出物 | 状态 |
|----------------|--------|------|
| Phase 1 Product Definition | `docs/superpowers/specs/2026-07-09-saas-prd.md` | ✅ |
| Phase 2 UI/UX Design | `docs/superpowers/specs/2026-07-09-saas-uiux-design.md` | ✅ |
| Phase 3 Tech Stack | `docs/superpowers/specs/2026-07-09-saas-tech-stack.md` | ✅ |
| Phase 4 Scaffolding | `docs/superpowers/specs/2026-07-09-saas-scaffolding.md` + 代码 | ✅ |
| Phase 5 TDD Remediation | `docs/superpowers/specs/2026-07-09-saas-quality-gate.md` | ✅ |
| Phase 6 Security Review | `docs/superpowers/specs/2026-07-09-saas-security-review.md` | ⚠️ 3 HIGH 遗留 |
| Phase 7 Quality Gate | 同上 | ✅ 400 passed |
| Phase 8 Visual UI Review | `docs/superpowers/specs/2026-07-09-saas-visual-ui-review.md` | ⚠️ 移动端改造待阶段 5 |
| Phase 9 Commit & Merge Review | 本文档 | ✅ CONDITIONAL APPROVE |
| Phase 10 Deploy & Iterate | 待创建 | ⏳ 待执行 |

---

## 8. 下一步

1. **是否提交代码？** 当前分支为 `feat/phase1-export-compliance-new`，未在默认分支，但提交/推送仍需你明确授权。
2. **进入 Phase 10**：验证 `docker compose up` 与 `/api/system/live` 健康检查。
3. **下阶段 HIGH 优先级**：修复 TaskQueue 租户级唯一约束与入队去重逻辑。

---

*本文档由 SaaS Dev Playbook Phase 9 生成。*
