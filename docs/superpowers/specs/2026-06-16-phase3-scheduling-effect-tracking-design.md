# Phase 3 设计：定时发送 + 效果追踪

> **阶段**: 3 / 6  
> **主题**: 定时发送 + 效果追踪  
> **依据**: `C:/Users/Administrator/Desktop/雷霆捕获系统_客户使用习惯审计报告.md`  
> **前置依赖**: Phase 1（导出/合规）+ Phase 2（Web 配置/Onboarding）已完成  
> **状态**: 已批准，待实施

---

## 1. 目标

让私信发送更安全、更可控；建立效果反馈闭环，让客户能够计算真实 ROI。

具体目标：
1. 支持项目级发送时段控制（如 9:00-21:00）、周末暂停、单日最大发送量。
2. 扩展线索状态机：`pending → sent → replied → converted → failed`。
3. 提供手动标记"已回复"/"已转化"入口，以及 Webhook 效果事件推送。
4. 在控制中心展示回复率/转化率，在线索池显示效果状态列。

---

## 2. 范围

### 2.1 包含

- 行业模型新增定时发送与效果追踪字段。
- Celery Beat 定时调度器（启动/暂停/触发发送批次）。
- `TaskQueue` 状态扩展与效果字段。
- 手动标记效果 API（已回复 / 已转化 / 撤销）。
- Webhook 效果事件推送（`lead.replied`, `lead.converted`）。
- 前端：项目配置"发送时段"面板、线索池效果列、控制中心转化指标。
- 相关单元/集成测试。

### 2.2 不包含

- 自动收件箱检查（Phase 3.1 先提供手动标记，自动检查作为后续增强）。
- 关键词报表 / A/B Test（Phase 4）。
- 移动端适配（Phase 5）。

---

## 3. 设计原则

- **最小侵入**：保留现有 DeviceWorker / Celery 发送链路，仅在入口加时段门控。
- **状态可逆**："已回复"/"已转化"支持撤销，避免误标记。
- **时区安全**：所有时间存储 UTC，前端按用户本地时区展示。
- **可观测**：调度事件、效果标记、Webhook 推送均记录日志。

---

## 4. 数据模型变更

### 4.1 `sa_industries` 表扩展

在 `server/models/industry.py` 的 `Industry` 模型中新增：

| 字段名 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `send_start_time` | `Time` | `09:00` | 每日允许发送开始时间（UTC） |
| `send_end_time` | `Time` | `13:00` | 每日允许发送结束时间（UTC） |
| `pause_weekends` | `Boolean` | `False` | 是否周末暂停 |
| `daily_send_max` | `Integer` | `0` | 单日最大发送量（0=不限制） |
| `effect_webhook_url` | `String(512)` | `""` | 效果事件 Webhook 地址 |

### 4.2 `IndustryConfig` 扩展

在 `core/config.py` 的 `IndustryConfig` dataclass 中同步新增：

```python
send_start_time: str = "09:00"
send_end_time: str = "13:00"
pause_weekends: bool = False
daily_send_max: int = 0
effect_webhook_url: str = ""
```

### 4.3 `sa_task_queue` 表扩展

在 `server/models/task.py` 的 `TaskQueue` 模型中新增：

| 字段名 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `replied_at` | `DateTime` | `None` | 对方回复时间 |
| `converted_at` | `DateTime` | `None` | 转化时间 |
| `reply_text` | `Text` | `""` | 对方回复内容快照 |
| `conversion_value` | `String(64)` | `""` | 转化价值（可选） |

### 4.4 状态迁移

```
pending ──(claim/send)──> sent ──(收到回复)──> replied ──(标记转化)──> converted
  │
  └──(发送失败)──> failed
```

- `done` 状态将逐步迁移为 `sent`，保持向后兼容。
- `failed` 状态保留。

---

## 5. API 设计

### 5.1 更新行业定时配置

```http
PUT /api/industries/{industry_id}/schedule-config
Content-Type: application/json
```

请求体：

```json
{
  "send_start_time": "09:00",
  "send_end_time": "21:00",
  "pause_weekends": true,
  "daily_send_max": 500,
  "effect_webhook_url": "https://crm.example.com/webhook/thunder-events"
}
```

### 5.2 启动 / 停止定时发送

```http
POST /api/industries/{industry_id}/schedule/start
POST /api/industries/{industry_id}/schedule/stop
```

响应：

```json
{
  "ok": true,
  "schedule_id": "thunder-send-recruitment",
  "next_run_at": "2026-06-16T09:00:00Z"
}
```

### 5.3 标记效果状态

```http
POST /api/leads/{lead_id}/mark-replied
Content-Type: application/json

{
  "reply_text": "多少钱？"
}
```

```http
POST /api/leads/{lead_id}/mark-converted
Content-Type: application/json

{
  "conversion_value": "1999"
}
```

```http
POST /api/leads/{lead_id}/unmark-converted
```

### 5.4 效果统计

```http
GET /api/stats/effects?industry_slug=recruitment&days=7
```

响应：

```json
{
  "industry_slug": "recruitment",
  "sent": 120,
  "replied": 18,
  "converted": 5,
  "reply_rate": 0.15,
  "conversion_rate": 0.042
}
```

---

## 6. 核心逻辑改动

### 6.1 时段门控

在 `core/task/worker.py` 的 `run_senders()` 合规检查之后、设备加载之前插入：

```python
from core.strategy.policy import is_send_window_open

if not is_send_window_open(industry):
    return {
        "ok": True,
        "skipped": True,
        "reason": "outside_send_window",
        "message": "当前不在允许的发送时段内。",
    }
```

`core/strategy/policy.py` 新增：

```python
def is_send_window_open(industry: IndustryConfig) -> bool:
    now = datetime.now(timezone.utc)
    if getattr(industry, "pause_weekends", False) and now.weekday() >= 5:
        return False
    start = _parse_time(getattr(industry, "send_start_time", "00:00"))
    end = _parse_time(getattr(industry, "send_end_time", "23:59"))
    current = now.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end
```

### 6.2 单日最大发送量门控

在 `MatrixTaskScheduler` 中，全局日配额基础上增加行业日发送上限检查。

### 6.3 Celery Beat 调度

在 `adapters/celery/app.py` 中配置 beat schedule：

```python
app.conf.beat_schedule = {
    "thunder-send-every-15min": {
        "task": "adapters.celery.send.run_send_batch",
        "schedule": crontab(minute="*/15"),
        "args": ("__all_active__", ""),
    },
}
```

`run_send_batch` 支持 `industry_slug="__all_active__"` 时自动遍历所有已启用调度的行业。

### 6.4 效果 Webhook 推送

新增 `server/services/effect_webhook.py`：

```python
def push_effect_event(event: str, industry_slug: str, lead: dict, webhook_url: str):
    payload = {
        "event": event,
        "industry_slug": industry_slug,
        "lead_id": lead["id"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if event == "lead.replied":
        payload["reply_text"] = lead.get("reply_text", "")
    elif event == "lead.converted":
        payload["conversion_value"] = lead.get("conversion_value", "")
    httpx.post(webhook_url, json=payload, timeout=10)
```

---

## 7. 前端改动

### 7.1 项目配置弹窗

新增"发送时段"折叠面板：
- 开始时间 / 结束时间（time input）
- 周末暂停开关
- 单日最大发送量
- 效果 Webhook URL

### 7.2 控制中心

新增效果指标卡片：
- 今日发送 / 回复 / 转化
- 回复率 / 转化率

### 7.3 线索池

新增列：
- 状态（sent / replied / converted / failed）
- 回复时间
- 转化时间
- 操作：标记已回复 / 标记已转化 / 撤销

---

## 8. 错误处理

| 场景 | 处理策略 |
|---|---|
| 当前不在发送时段 | `run_senders` 返回 `skipped=True`，不调度设备 |
| 周末暂停 | 同上 |
| 达到单日最大发送量 | scheduler 返回 `daily_max_reached` |
| 效果 Webhook 失败 | 记录日志，不影响标记操作 |
| 撤销已转化 | 将 `converted_at` 置空，重新计算转化率 |

---

## 9. 测试计划

### 9.1 后端测试

- `is_send_window_open` 在不同时段、周末场景下的行为。
- `PUT /api/industries/{id}/schedule-config` 保存正确。
- 标记效果 API 正确更新 `TaskQueue` 字段。
- 效果统计 API 正确计算回复率/转化率。
- Celery `run_send_batch` 在 `__all_active__` 模式下遍历行业。

### 9.2 前端测试

手动验证：
- 项目弹窗发送时段面板可保存。
- 线索池显示效果列和操作按钮。
- 控制中心展示效果指标。

### 9.3 回归测试

- `python -m pytest tests/` 全部通过。

---

## 10. 风险与回滚

| 风险 | 缓解措施 |
|---|---|
| 定时任务在错误时间触发 | 所有时间按 UTC 存储，前端按本地时区展示 |
| 状态机变更导致旧数据不兼容 | `done` 状态视为 `sent`，新增字段均有默认值 |
| 发送时段限制影响用户体验 | 默认 00:00-23:59，不开启周末暂停 |

---

## 11. 后续阶段衔接

本阶段完成后：
- Phase 4 可基于效果数据进行关键词报表和 A/B Test。
- Phase 6 云端 SaaS 可直接复用定时调度与效果统计。
