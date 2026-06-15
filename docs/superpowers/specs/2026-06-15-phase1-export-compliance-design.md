# 阶段 1 设计方案：数据导出 + 合规模式

## 1. 背景与目标

根据《雷霆捕获系统客户使用习惯审计报告》，当前产品在**商业化就绪度**上存在两个最紧迫的 P0 缺口：

1. **数据导出缺失**：客户经理无法将线索导出为 Excel/CSV 给销售团队或老板汇报。
2. **合规风险过高**：系统自动采集评论并批量发送私信，存在平台封号与合规争议；客户需要一种"只采集、不发送"的合规模式，输出高意向线索供人工触达。

本阶段目标是在**不破坏原有 AI 自动私信能力**的前提下，以最小侵入式改动补齐这两个 P0 能力。

## 2. 范围

### 2.1 包含在本阶段

- 线索池 Excel/CSV 导出 API 与前端按钮
- 项目级"合规模式"开关（只采集不发送）
- Webhook 推送配置与测试接口（可选，用于 CRM 对接）
- 前端文案与按钮状态适配
- 相关单元/集成测试

### 2.2 不包含在本阶段

- 完整的 CRM 双向对接（仅单向 Webhook 推送）
- 线索"已导出"状态持久化（本阶段通过导出文件/日志记录）
- 多租户权限隔离增强
- 移动端响应式适配
- 发送效果追踪（回复率、转化率）

## 3. 设计原则

- **加法优先**：所有改动均为新增能力，原有采集、分类、发送链路完整保留。
- **最小侵入**：尽量在现有入口点做判断，不重构核心发送状态机。
- **可观测**：合规模式跳过发送、Webhook 推送结果均写入日志，便于审计。
- **向后兼容**：数据库新增字段均有默认值，旧数据无需迁移即可正常工作。

## 4. 数据模型变更

### 4.1 `sa_industries` 表扩展

在 `server/models/industry.py` 的 `Industry` 模型中新增以下字段：

| 字段名 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `compliance_mode` | `Boolean` | `False` | 是否开启合规模式（只采集不发送） |
| `webhook_url` | `String(512)` | `""` | 线索推送 Webhook 地址 |
| `auto_export_enabled` | `Boolean` | `False` | 分类完成后是否自动触发 Webhook 推送 |

### 4.2 `IndustryConfig` 扩展

在 `core/config.py` 的 `IndustryConfig` dataclass 中同步新增：

```python
compliance_mode: bool = False
webhook_url: str = ""
auto_export_enabled: bool = False
```

## 5. API 设计

### 5.1 线索导出

```http
POST /api/leads/export
Content-Type: application/json
```

请求体：

```json
{
  "industry_slug": "recruitment",
  "status": "pending",
  "format": "xlsx",
  "limit": 5000,
  "fields": ["platform", "keyword", "user_name", "text", "ai_reply", "status", "fetched_at"]
}
```

响应：直接返回文件流（`Content-Disposition: attachment; filename=leads_20260615_143022.xlsx`）。

导出字段清单：

| 字段 | 说明 |
|---|---|
| `id` | 线索内部 ID |
| `platform` | 平台（douyin/xiaohongshu） |
| `keyword` | 来源关键词 |
| `source_creator` | 博主昵称 |
| `source_video_desc` | 视频描述 |
| `user_name` | 评论用户昵称 |
| `unique_id` / `short_id` / `douyin_id` | 平台用户标识 |
| `text` | 评论原文 |
| `matched_categories` | 意图分类与置信度（JSON） |
| `ai_reply` | 系统生成的 AI 回复文案 |
| `status` | 线索状态 |
| `error` | 失败原因 |
| `fetched_at` | 采集时间 |
| `processed_at` | 处理/发送时间 |

### 5.2 Webhook 配置与测试

```http
PUT /api/industries/{industry_id}/compliance-config
Content-Type: application/json
```

请求体：

```json
{
  "compliance_mode": true,
  "webhook_url": "https://crm.example.com/webhook/thunder-leads",
  "auto_export_enabled": true
}
```

```http
POST /api/industries/{industry_id}/webhook-test
```

响应：

```json
{
  "ok": true,
  "status_code": 200,
  "response_preview": "ok"
}
```

### 5.3 获取行业合规配置

`GET /api/industries/{industry_id}` 和 `GET /api/industries` 的返回中自动包含新增字段（通过 `IndustryOut` schema 扩展）。

## 6. 核心逻辑改动

### 6.1 发送入口合规拦截

修改位置：`core/task/worker.py` 中的 `run_senders()`。

在函数入口处增加：

```python
if getattr(industry, "compliance_mode", False):
    log.info("Compliance mode enabled for %s; skipping actual send.", industry.slug)
    # 可选：触发自动 Webhook 推送
    _notify_compliance_webhook(industry)
    return {
        "ok": True,
        "skipped": True,
        "reason": "compliance_mode",
        "industry_slug": industry.slug,
        "message": "合规模式已开启，仅采集不发送。",
    }
```

该拦截点位于 Celery 调度之前，因此无论是线程模式还是 Celery 模式都会生效。

### 6.2 Webhook 推送

新增 `server/services/webhook.py`：

- `push_leads_to_webhook(industry, leads)`: 将线索列表 POST 到 `industry.webhook_url`
- 使用 `httpx` 或 `requests` 异步/线程方式发送
- 记录推送结果到 `sa_action_log` 或新增 `sa_webhook_log`

触发时机：

1. `auto_export_enabled=True` 且分类完成时（在 `enqueue_classified()` 后异步调用）
2. 手动点击 Webhook 测试按钮时

## 7. 前端改动

### 7.1 项目配置弹窗

- 在"矩阵高级设置"或新增"合规与导出"折叠面板中：
  - 增加"合规模式"开关
  - 增加 Webhook URL 输入框
  - 增加"分类完成后自动推送"开关
  - 增加"测试 Webhook"按钮

### 7.2 控制中心

- 当所选项目开启合规模式时：
  - 隐藏"发送"按钮
  - 显示"导出高意向线索"按钮（跳转线索池并自动打开导出弹窗）
  - 在就绪度面板显示合规提示："合规模式：只采集不发送，线索可导出或推送至 CRM"

### 7.3 线索池页面

- 在过滤器区域增加"导出 Excel"和"导出 CSV"按钮
- 点击后弹出字段选择/确认框
- 导出过程中显示 loading，完成后 Toast 提示

## 8. 错误处理

| 场景 | 处理策略 |
|---|---|
| 导出数据量过大 | 采用流式生成；超过 10000 条时提示用户缩小筛选范围 |
| Webhook 推送失败 | 记录失败日志，前端测试接口显示具体 HTTP 状态码和响应片段 |
| 合规模式下误触发发送 | 在 `run_senders` 入口拦截，返回明确信息，不进入设备调度 |
| 旧数据缺少新增字段 | 数据库默认值兼容，无需手动迁移 |

## 9. 测试计划

### 9.1 后端测试

- 合规模式开启时，调用 `/api/industries/{id}/send` 不调度设备
- 导出 API 按不同格式、状态筛选返回正确文件
- Webhook 测试接口正确发送测试 payload
- `IndustryConfig` 从数据库模型正确转换，包含新增字段

### 9.2 前端测试

- 合规模式下"发送"按钮隐藏，"导出"按钮显示
- 导出弹窗字段选择生效
- Webhook 配置保存与测试反馈正常

### 9.3 集成测试

- 完整流程：创建合规模式项目 -> 采集 -> 分类 -> 点击"导出" -> 验证 Excel 字段

## 10. 风险与回滚

| 风险 | 缓解措施 |
|---|---|
| 新增字段导致 SQLAlchemy create_all 失败 | 使用 `Boolean`/`String` 等通用类型，PostgreSQL/SQLite 均兼容 |
| 合规模式误拦截正常发送 | 拦截逻辑仅判断 `compliance_mode=True`，默认值 false 不影响旧项目 |
| 导出大文件导致内存占用高 | 使用生成器 + 流式响应，限制单次导出上限 |
| Webhook 泄露敏感数据 | Webhook payload 仅包含线索业务字段，不含 API Key；URL 仅管理员可见 |

**回滚方案**：若出现严重问题，可通过数据库将 `compliance_mode` 改回 `False`，并注释掉新增 API 路由恢复旧行为。

## 11. 后续阶段衔接

本阶段完成后，为以下阶段奠定基础：

- **阶段 3（定时发送 + 效果追踪）**：可在合规模式之外，增加发送时段控制与回复状态回写。
- **阶段 4（关键词报表 + A/B Test）**：导出的线索数据可作为分析数据源。
- **阶段 6（云端 SaaS 版本）**：Webhook 与导出能力是 SaaS 多租户客户必要的集成接口。
