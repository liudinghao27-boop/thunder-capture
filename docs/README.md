# Thunder Capture 项目文档中心

本目录存放雷霆捕获系统（Thunder Capture）的产品设计、实施计划、标准流程与审计记录。

---

## 目录结构

```
docs/
├── README.md                                    # 本文档：文档索引与使用指南
└── superpowers/                                 # 研发管理文档（设计/计划/SOP/审计）
    ├── archive/                                 # 归档文件（自动生成的会话状态等）
    │   └── memory/
    │       └── 2026-06-16-session-state.md
    ├── audits/                                  # 代码审计与安全审计报告
    │   └── 2026-06-16-code-audit-report.md
    ├── plans/                                   # 各阶段实施计划
    │   ├── 2026-06-15-phase1-export-compliance-plan.md
    │   ├── 2026-06-15-phase2-web-config-onboarding-plan.md
    │   ├── 2026-06-16-phase3-scheduling-effect-tracking-plan.md
    │   └── 2026-06-16-phase4-analytics-abtest-plan.md
    ├── sops/                                    # 标准操作流程与路线图
    │   └── 2026-06-15-commercialization-roadmap-sop.md
    └── specs/                                   # 各阶段设计规格说明书
        ├── 2026-06-15-phase1-export-compliance-design.md
        ├── 2026-06-15-phase2-web-config-onboarding-design.md
        ├── 2026-06-16-phase3-scheduling-effect-tracking-design.md
        └── 2026-06-16-phase4-analytics-abtest-design.md
```

---

## 各目录说明

| 目录 | 用途 | 读者 |
|------|------|------|
| `superpowers/specs/` | 需求分析、架构设计、API 契约、数据模型设计 | 产品经理、架构师、后端开发 |
| `superpowers/plans/` | 可执行的实施计划，包含步骤、命令、测试用例 | 开发工程师、AI Agent |
| `superpowers/sops/` | 商业化路线图、交付标准、运维 SOP | 项目经理、交付团队 |
| `superpowers/audits/` | 代码审计、安全审计、性能审计报告 | 技术负责人、安全工程师 |
| `superpowers/archive/` | 自动生成的会话状态、历史快照等低活跃文件 | 维护者 |

---

## 命名规范

```
YYYY-MM-DD-[topic]-[type].md
```

- `YYYY-MM-DD`：文档创建或主要更新日期
- `topic`：主题，如 `phase1-export-compliance`、`code-audit`
- `type`：文档类型，如 `design`（设计）、`plan`（计划）、`sop`（流程）、`report`（报告）

---

## 使用指南

### 新增功能时

1. 在 `superpowers/specs/` 下编写设计文档
2. 在 `superpowers/plans/` 下编写实施计划
3. 开发完成后，在 `superpowers/sops/` 或 `superpowers/audits/` 更新状态或审计记录

### 查找历史决策

- 按阶段查：`superpowers/specs/` 和 `superpowers/plans/` 中的文件名包含阶段号
- 按主题查：使用 `grep -R "关键词" docs/superpowers/`
- 查最新状态：`superpowers/sops/2026-06-15-commercialization-roadmap-sop.md`

### 归档规则

以下文件应移入 `superpowers/archive/`：

- 自动生成的会话状态/记忆文件
- 已过期且不再维护的设计草稿
- 合并到其他文档后的历史版本

---

## 已清理的冗余文件

本次整理已删除：

- `docs/examples/` — 与项目无关的 c4a 教程示例脚本
- `docs/md_v2/` — 与 `docs/examples/` 重复的 c4a 脚本副本
- `docs/superpowers/memory/` — 会话状态记忆文件已归档至 `superpowers/archive/memory/`
