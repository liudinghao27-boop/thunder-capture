# 雷霆捕获系统 Phase 6 安全审查报告

> **文档版本**：v1.0  
> **创建日期**：2026-07-09  > **审查范围**：Phase 5 TDD 修复引入的变更（多租户隔离）  
> **审查人**：security-reviewer agent + Claude Code

---

## 1. 审查结论

**总体 verdict：WARN（带条件通过）**

Phase 5 的多租户隔离修复在 API 层和任务流水线层面基本正确，安全审查发现的 **1 项 CRITICAL** 问题已修复。剩余 **3 项 HIGH** 问题已识别并记录，建议在阶段 6 后续或阶段 7 之前逐项处理。

---

## 2. 已修复问题

### CRITICAL：CollectedVideo / CollectorState 缺少 `owner_user_id`

| 项目 | 内容 |
|------|------|
| 风险 | 去重和采集状态全局共享，租户间可互相影响 |
| 修复文件 | `server/models/task.py`、`server/services/task_stats.py`、`server/services/migrations.py` |
| 修复内容 | 两模型新增 `owner_user_id`；唯一约束包含 `owner_user_id`；相关函数按租户过滤 |
| 验证 | `tests/server/services/test_task_stats.py` 新增 9 个隔离测试；全量测试 400 passed |

---

## 3. 遗留 HIGH 问题

| 编号 | 问题 | 位置 | 建议修复 | 计划阶段 |
|------|------|------|----------|----------|
| HIGH-1 | 迁移回填对共享 slug 使用 `MAX(sa_industries.user_id)` 任意分配所有权 | `server/services/migrations.py:_backfill_owner_user_id` | 对共享 slug 拒绝分配，留空并告警，要求人工清理 | 阶段 6 收尾 |
| HIGH-2 | `core/discover.py:run_discovery` 无租户上下文，CLI/未来 API 直接调用会写入空 `owner_user_id` | `core/discover.py` | 显式传入 `owner_user_id` 并断言非空 | 阶段 6 收尾 |
| HIGH-3 | Celery 任务 `user_id` 为明文参数，可被伪造/重放 | `adapters/celery/send.py` | 使用 `itsdangerous.TimestampSigner` 签名任务 payload | 阶段 6 收尾或阶段 7 |

---

## 4. 手动检查清单

- [x] 无硬编码密钥（扫描 diff 范围）
- [x] 用户输入通过 Pydantic schema 校验
- [x] SQL 查询使用 ORM/参数化（无字符串拼接）
- [x] 认证：JWT `get_current_user`
- [x] 授权：按 `user_id`/`owner_user_id` 过滤已落地
- [x] 速率限制：`RateLimitMiddleware` 已启用
- [x] 错误信息不泄露敏感数据
- [ ] CSRF：当前为同源 SPA + JWT，后续云端 SaaS 需评估 CSRF 风险

---

## 5. 扫描器建议（未实际运行）

| 工具 | 用途 | 建议接入阶段 |
|------|------|--------------|
| Gitleaks | 检测 git 中的密钥泄露 | CI 即时 |
| Semgrep | SAST 检测注入、auth 缺陷 | CI |
| Trivy | 依赖漏洞、容器镜像扫描 | CI/CD |
| Checkov | Docker Compose / K8s 配置检查 | 阶段 6 部署前 |

---

## 6. 下一步

1. 处理 HIGH-1/2/3 后重新运行 security-reviewer。
2. 将 Gitleaks/Semgrep/Trivy 接入 CI。
3. 进入 Phase 7 质量门禁。

---

*本文档由 SaaS Dev Playbook Phase 6 生成。*
