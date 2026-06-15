# Phase 2 设计：Web 化配置 + 新手引导

> **阶段**: 2 / 6  
> **主题**: Web 化配置 + 新手引导  
> **依据**: `C:/Users/Administrator/Desktop/雷霆捕获系统_客户使用习惯审计报告.md`  
> **前置依赖**: Phase 1（数据导出 + 合规模式）已完成并通过测试  
> **状态**: 已批准，待实施

---

## 1. 目标

消除 YAML 编辑，让非技术运营人员能在网页上完成项目配置；降低首次上手门槛，使用户在首次登录后 5 分钟内完成第一个获客项目创建。

---

## 2. 范围

### 2.1 包含

- 前端项目配置弹窗补齐（意图词、噪声词、目标用户、客户分类的可视化编辑）。
- 字段分组与术语翻译（技术术语 → 业务语言）。
- 首次登录新手引导（Onboarding Wizard）。
- 后端就绪度检查 API。
- 弃用运行时 YAML 作为用户行业配置来源（保留 `config/industries/_template.yaml` 作为只读模板）。
- 新增/更新的自动化测试。

### 2.2 不包含

- 完全重构配置版本化 / 草稿机制（避免与 Phase 3/6 重叠）。
- 移动端 UI 适配（Phase 5）。
- 定时任务 / 效果追踪（Phase 3）。

---

## 3. 方案选择

| 方案 | 概述 | 结论 |
|---|---|---|
| A | 表单补齐 + 新手引导 + 弃用运行时 YAML | **采用**。改动最小，直接解决审计报告中的配置摩擦和上手门槛问题。 |
| B | 完全弃用 YAML + 配置版本化 | 工作量过大，影响 CLI 与采集引擎，延后到后续阶段。 |
| C | 三步配置向导 + AI 一键生成 | 交互改动深，测试成本高，可作为 Phase 2 完成后的小幅优化。 |

---

## 4. 后端设计

### 4.1 模型与 Schema

- `IndustryUpdate` 已支持所有字段的 Optional 更新，无需新增模型字段。
- 确保 `intent_keywords`、`noise_keywords`、`target_users`、`categories` 可通过 `PUT /api/industries/{id}` 批量更新。
- 增加 schema 校验：
  - `intent_keywords` / `noise_keywords` / `target_users` 归一化为去重字符串列表。
  - `categories` 去重且非空时至少保留 1 个分类。

### 4.2 新增 API

`GET /api/industries/{industry_id}/ready-state`

返回项目是否可运行采集/发送的就绪状态：

```json
{
  "ok": true,
  "industry_id": "...",
  "score": 75,
  "checks": {
    "has_keywords": true,
    "has_intent_keywords": true,
    "has_noise_keywords": true,
    "has_categories": true,
    "has_reply_persona": true,
    "has_api_key": true,
    "has_device": false,
    "compliance_ready": true
  },
  "next_step": "请至少添加一台活跃设备"
}
```

检查项：
- `has_keywords`: `keywords` 非空。
- `has_intent_keywords`: `intent_keywords` 非空。
- `has_noise_keywords`: `noise_keywords` 非空。
- `has_categories`: `categories` 非空。
- `has_reply_persona`: `reply_tone` 与 `reply_style` 非空。
- `has_api_key`: 当前用户或系统配置中存在可用 LLM API Key。
- `has_device`: 当前用户下存在 `is_active=True` 的设备。
- `compliance_ready`: 合规模式下 `webhook_url` 已配置。

### 4.3 YAML 处理

- 保留 `config/industries/_template.yaml` 与示例 YAML 作为文档和模板。
- 系统启动和运行时不再从 `config/industries/*.yaml` 加载用户行业配置。
- 若 CLI 当前仍读取 YAML，需在 CLI 调用时优先使用 DB 中 `Industry` 配置，YAML 仅作为向后兼容的 fallback（本次设计选择完全移除 CLI 对 YAML 的依赖）。

---

## 5. 前端设计

### 5.1 项目配置弹窗

#### 字段分组

- **基础配置**（默认展开）
  - 项目名称（原 `name`）
  - 项目标识（原 `slug`，新建时填写，编辑时只读）
  - 业务描述（AI 生成用，不保存到 DB）
  - 采集平台（原 `platforms`，单选）

- **关键词漏斗**（默认展开）
  - 搜索关键词（原 `keywords`，多行/标签输入）
  - 意图词（新增标签输入：`intent_keywords`）
  - 噪声词（新增标签输入：`noise_keywords`）
  - 目标用户（新增标签输入：`target_users`）
  - 客户分类（新增标签输入：`categories`）

- **回复人设**（默认展开）
  - 回复人设（原 `reply_tone`）
  - 回复风格（原 `reply_style`）
  - 钩子话术（原 `reply_hook`）

- **采集策略**（默认折叠：高级）
  - 视频时效（原 `video_max_age_days`）
  - 评论时效（原 `comment_max_age_hours`）
  - 每轮采集视频数（原 `collect_video_limit`）
  - 每轮采集作者数（原 `collect_authors_per_run`）
  - 关键词批次大小（原 `keyword_batch_size`）

- **发送策略**（默认折叠：高级）
  - 每设备日发上限（原 `daily_limit`）
  - 目标设备数（原 `matrix_target_devices`）
  - 库存天数（原 `lead_inventory_days`）
  - 全局日发上限（原 `global_daily_limit`）
  - 自动补采开关（原 `auto_replenish_enabled`）
  - 补采阈值天数（原 `replenish_threshold_days`）

- **合规设置**（Phase 1 已实现，保留并优化文案）
  - 合规模式（只采集不发送）
  - Webhook URL
  - 自动导出

#### 标签输入组件

为 `intent_keywords`、`noise_keywords`、`target_users`、`categories` 实现通用标签输入：
- 支持回车、逗号、Tab 添加标签。
- 支持 Backspace 删除最后一个标签。
- 自动去重、去空。
- 每个标签可单独删除。

#### 术语翻译

| 原术语 | 界面文案 |
|---|---|
| slug | 项目标识 |
| matrix_target_devices | 目标设备数 |
| daily_limit | 每设备日发上限 |
| global_daily_limit | 全局日发上限 |
| lead_inventory_days | 库存天数 |
| keyword_batch_size | 关键词批次大小 |
| collect_authors_per_run | 每轮采集作者数 |
| collect_video_limit | 每轮采集视频数 |
| video_max_age_days | 视频时效（天） |
| comment_max_age_hours | 评论时效（小时） |
| auto_replenish_enabled | 自动补采 |
| replenish_threshold_days | 补采阈值（天） |
| intent_keywords | 意图词 |
| noise_keywords | 噪声词 |
| target_users | 目标用户 |
| categories | 客户分类 |

### 5.2 新手引导（Onboarding）

首次登录（本地存储 `thunder_onboarding_seen` 为 false 时）显示分步引导浮层：

1. **欢迎**（1/4）
   - 标题：欢迎来到雷霆捕获系统
   - 内容：3 句话介绍系统价值。
   - 操作：下一步

2. **配置 API Key**（2/4）
   - 说明：系统需要 LLM API Key 来分类评论意图。
   - 操作：跳转到“系统设置”页签；或跳过（后续在设置中补全）。

3. **添加设备**（3/4）
   - 说明：需要至少一台 Android 设备连接 ADB。
   - 操作：跳转到“设备”页签；或跳过。

4. **创建项目**（4/4）
   - 说明：点击“新建项目”，用 AI 生成配置并保存。
   - 操作：打开项目配置弹窗；完成。

每一步高亮下一步按钮；若前置条件未满足，显示提示但不阻塞。

引导完成后设置 `localStorage.thunder_onboarding_seen = "true"`。

### 5.3 控制中心就绪度提示

在“控制中心”增加动态提示：
- 若当前项目就绪度不足，显示 `next_step` 提示和快捷操作按钮。
- 例如：未配置 API Key → “请先配置 API Key” + 跳转设置。

---

## 6. 数据流

```
用户打开项目弹窗
  │
  ▼
前端标签输入组件管理 intent/noise/target/categories
  │
  ▼
PUT /api/industries/{id} 或 POST /api/industries
  │
  ▼
Pydantic schema 归一化 → SQLAlchemy 写入 DB
  │
  ▼
GET /api/industries/{id}/ready-state 返回检查项
  │
  ▼
前端控制中心根据 ready-state 显示下一步行动
```

---

## 7. 测试计划

### 7.1 后端测试

- `tests/server/test_industries.py`：
  - 更新行业时 `intent_keywords` / `noise_keywords` / `target_users` / `categories` 正确保存和去重。
  - `GET /api/industries/{id}/ready-state` 各检查项正确。
  - 无设备时 `has_device=false`。
  - 合规模式下缺少 webhook 时 `compliance_ready=false`。

### 7.2 前端测试

- 手动验证清单（写入 spec 附录）：
  - 标签输入组件：回车、逗号、Tab 添加；Backspace 删除；去重。
  - 项目弹窗高级分组默认折叠/展开。
  - 首次登录出现 Onboarding；完成后不再出现。
  - 术语替换后无技术英文残留。

### 7.3 回归测试

- `python -m pytest tests/` 全部通过。

---

## 8. 验收标准

- [ ] 用户无需编辑 YAML 即可完整配置一个项目。
- [ ] 新用户首次登录看到引导，5 分钟内可完成第一个项目创建。
- [ ] 所有配置字段保存后能正确用于采集/分类/发送流程。
- [ ] `python -m pytest tests/` 通过。
- [ ] 运行时不再依赖 `config/industries/*.yaml` 中的用户配置。

---

## 9. 风险与回滚

| 风险 | 缓解措施 |
|---|---|
| YAML 与 DB 配置不同步 | 本次直接弃用运行时 YAML，启动时只读 DB；保留模板供参考。 |
| 表单字段过多导致用户困惑 | 按“基础/高级”分组，默认折叠高级。 |
| 新手引导打断老用户 | 仅首次登录显示，可跳过；老用户不受影响。 |
| CLI 仍依赖 YAML | 同步更新 CLI 读取逻辑，优先从 DB 查询行业配置。 |

---

## 10. 附录：手动验证清单

1. 清空浏览器 localStorage，刷新页面，确认 Onboarding 出现。
2. 跟随引导完成 API Key → 设备 → 项目三步（或跳过前两步直接创建项目）。
3. 新建项目时，在“关键词漏斗”中输入意图词、噪声词、目标用户、客户分类，保存后重新打开确认值 retained。
4. 进入“控制中心”，确认就绪度提示与下一步行动按钮显示正确。
5. 运行 `python -m pytest tests/ -q` 确认无回归。
