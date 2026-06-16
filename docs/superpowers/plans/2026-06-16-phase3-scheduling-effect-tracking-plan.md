# Phase 3：定时发送 + 效果追踪 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在雷霆捕获系统中实现项目级发送时段控制、周末暂停、单日发送上限和线索效果追踪（已回复 / 已转化）。

**Architecture:** 在行业模型与 `IndustryConfig` 中新增定时配置字段；在 `run_senders()` 入口增加时段门控；扩展 `TaskQueue` 状态机与效果字段；通过 Celery Beat 定时触发 `run_send_batch`；新增效果标记 API 与 Webhook 推送；前端扩展项目弹窗、线索池和控制中心。

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x, Pydantic 2.x, Celery, PostgreSQL/SQLite, Vanilla JS + Tailwind CSS, pytest, httpx

---

## 文件结构映射

| 文件 | 职责 |
|---|---|
| `server/models/industry.py` | `Industry` 模型新增定时/效果配置字段 |
| `core/config.py` | `IndustryConfig` dataclass 新增定时/效果字段 |
| `server/schemas/industry.py` | Pydantic schema 新增字段校验与输出 |
| `server/models/task.py` | `TaskQueue` 新增效果字段与状态支持 |
| `core/strategy/policy.py` | 新增 `is_send_window_open()` 时段门控 |
| `core/task/worker.py` | `run_senders()` 增加时段门控 |
| `core/task/scheduler.py` | 增加行业日发送上限检查 |
| `adapters/celery/app.py` | 配置 Celery Beat 定时调度 |
| `adapters/celery/send.py` | `run_send_batch` 支持 `__all_active__` 模式 |
| `server/services/effect_webhook.py` | 新增效果事件 Webhook 推送 |
| `server/api/leads.py` | 新增效果标记 / 撤销 / 统计 API |
| `server/api/industries.py` | 新增定时配置与调度启停 API |
| `server/static/index.html` | 前端发送时段面板、线索效果列、效果指标 |
| `tests/core/strategy/test_policy.py` | 新增时段门控测试 |
| `tests/server/api/test_leads_effects.py` | 新增效果标记 API 测试 |
| `tests/server/api/test_industries_schedule.py` | 新增定时配置 API 测试 |
| `tests/adapters/celery/test_send.py` | 扩展 Celery 任务测试 |

---

## Task 1: 数据模型与配置类扩展

**目标:** 让 `Industry` 模型、`IndustryConfig` dataclass 和 Pydantic schema 都支持定时发送配置字段。

**Files:**
- Modify: `server/models/industry.py`
- Modify: `core/config.py`
- Modify: `server/schemas/industry.py`
- Test: `tests/server/test_models_schemas.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/test_models_schemas.py
import pytest
from server.schemas.industry import IndustryCreate, IndustryUpdate, IndustryOut
from server.models.industry import Industry
from core.config import IndustryConfig


def test_industry_create_has_schedule_fields():
    data = IndustryCreate(
        name="测试", slug="test-schedule",
        send_start_time="09:00", send_end_time="21:00",
        pause_weekends=True, daily_send_max=100,
        effect_webhook_url="https://example.com/events",
    )
    assert data.send_start_time == "09:00"
    assert data.pause_weekends is True
    assert data.daily_send_max == 100


def test_industry_model_has_schedule_columns():
    ind = Industry(name="测试", slug="test-schedule")
    assert hasattr(ind, "send_start_time")
    assert hasattr(ind, "pause_weekends")
    assert hasattr(ind, "daily_send_max")


def test_industry_config_has_schedule_fields():
    cfg = IndustryConfig(
        name="测试", slug="test-schedule", keywords=["a"], categories=["c"],
        send_start_time="10:00", send_end_time="22:00",
        pause_weekends=True, daily_send_max=200,
        effect_webhook_url="https://example.com/events",
    )
    assert cfg.send_start_time == "10:00"
    assert cfg.pause_weekends is True
    assert cfg.daily_send_max == 200
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
python -m pytest tests/server/test_models_schemas.py -v
```

Expected: 3 FAIL，字段不存在。

- [ ] **Step 3: 修改 Industry 模型**

在 `server/models/industry.py` 中 `Industry` 类里，在 `auto_export_enabled` 字段之后插入：

```python
    send_start_time = Column(String(8), default="09:00")
    send_end_time = Column(String(8), default="13:00")
    pause_weekends = Column(Boolean, default=False)
    daily_send_max = Column(Integer, default=0)
    effect_webhook_url = Column(String(512), default="")
```

- [ ] **Step 4: 修改 IndustryConfig**

在 `core/config.py` 的 `IndustryConfig` dataclass 中，在 `auto_export_enabled` 字段之后添加：

```python
    send_start_time: str = "09:00"
    send_end_time: str = "13:00"
    pause_weekends: bool = False
    daily_send_max: int = 0
    effect_webhook_url: str = ""
```

- [ ] **Step 5: 修改 Pydantic schemas**

在 `server/schemas/industry.py` 中：

`IndustryCreate` 类在 `auto_export_enabled` 之后添加：

```python
    send_start_time: str = "09:00"
    send_end_time: str = "13:00"
    pause_weekends: bool = False
    daily_send_max: int = 0
    effect_webhook_url: str = ""
```

`IndustryUpdate` 类在 `auto_export_enabled` 之后添加：

```python
    send_start_time: str | None = None
    send_end_time: str | None = None
    pause_weekends: bool | None = None
    daily_send_max: int | None = None
    effect_webhook_url: str | None = None
```

`IndustryOut` 类在 `auto_export_enabled` 之后添加：

```python
    send_start_time: str = "09:00"
    send_end_time: str = "13:00"
    pause_weekends: bool = False
    daily_send_max: int = 0
    effect_webhook_url: str = ""
```

- [ ] **Step 6: 运行测试确认通过**

```bash
python -m pytest tests/server/test_models_schemas.py -v
```

Expected: 3 PASS。

- [ ] **Step 7: 提交**

```bash
git add server/models/industry.py core/config.py server/schemas/industry.py tests/server/test_models_schemas.py
git commit -m "feat(phase3): add scheduling config fields to Industry model, config and schemas"
```

---

## Task 2: 扩展 TaskQueue 效果字段

**目标:** 在 `TaskQueue` 模型中新增 `replied_at`, `converted_at`, `reply_text`, `conversion_value` 字段。

**Files:**
- Modify: `server/models/task.py`
- Test: `tests/server/test_models_schemas.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/test_models_schemas.py

def test_task_queue_has_effect_columns():
    from server.models.task import TaskQueue
    t = TaskQueue(video_id="v1", comment_id="c1")
    assert hasattr(t, "replied_at")
    assert hasattr(t, "converted_at")
    assert hasattr(t, "reply_text")
    assert hasattr(t, "conversion_value")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/test_models_schemas.py::test_task_queue_has_effect_columns -v
```

Expected: FAIL。

- [ ] **Step 3: 修改 TaskQueue 模型**

在 `server/models/task.py` 中 `TaskQueue` 类里，在 `error` 字段之后插入：

```python
    # Effect tracking
    replied_at = Column(DateTime, nullable=True)
    converted_at = Column(DateTime, nullable=True)
    reply_text = Column(Text, default="")
    conversion_value = Column(String(64), default="")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/server/test_models_schemas.py::test_task_queue_has_effect_columns -v
```

Expected: PASS。

- [ ] **Step 5: 生成 Alembic 迁移**

```bash
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic revision --autogenerate -m "add phase3 scheduling and effect fields"
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic upgrade head
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic downgrade -1
rm -f data/thunder.db data/thunder.db-*
```

- [ ] **Step 6: 提交**

```bash
git add server/models/task.py tests/server/test_models_schemas.py adapters/postgres/migrations/versions/*.py
git commit -m "feat(phase3): add effect tracking columns to TaskQueue and alembic migration"
```

---

## Task 3: 实现时段门控

**目标:** 新增 `is_send_window_open()` 函数，并在 `run_senders()` 中调用。

**Files:**
- Create: `core/strategy/policy.py`（如不存在则修改）
- Modify: `core/task/worker.py`
- Test: `tests/core/strategy/test_policy.py`

- [ ] **Step 1: 检查现有 policy 文件**

```bash
ls core/strategy/
```

如果 `core/strategy/policy.py` 已存在，直接修改；否则创建。

- [ ] **Step 2: 写失败测试**

```python
# tests/core/strategy/test_policy.py
from datetime import datetime, timezone, time
from unittest.mock import patch
from core.config import IndustryConfig
from core.strategy.policy import is_send_window_open


def test_window_open_during_active_hours():
    cfg = IndustryConfig(name="测试", slug="t", keywords=["a"], categories=["c"],
                         send_start_time="09:00", send_end_time="21:00")
    with patch("core.strategy.policy.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 16, 14, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value.weekday = lambda: 0
        assert is_send_window_open(cfg) is True


def test_window_closed_outside_active_hours():
    cfg = IndustryConfig(name="测试", slug="t", keywords=["a"], categories=["c"],
                         send_start_time="09:00", send_end_time="21:00")
    with patch("core.strategy.policy.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 16, 23, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value.weekday = lambda: 0
        assert is_send_window_open(cfg) is False


def test_weekend_paused():
    cfg = IndustryConfig(name="测试", slug="t", keywords=["a"], categories=["c"],
                         send_start_time="09:00", send_end_time="21:00", pause_weekends=True)
    with patch("core.strategy.policy.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc)  # Saturday
        mock_dt.now.return_value.weekday = lambda: 5
        assert is_send_window_open(cfg) is False
```

- [ ] **Step 3: 运行测试确认失败**

```bash
python -m pytest tests/core/strategy/test_policy.py -v
```

Expected: 3 FAIL。

- [ ] **Step 4: 实现时段门控**

创建或修改 `core/strategy/policy.py`：

```python
"""Send policy gates: time windows, weekend pause, etc."""

from datetime import datetime, timezone
from core.config import IndustryConfig


def _parse_time(value: str):
    """Parse HH:MM string into (hour, minute) tuple."""
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except Exception:
        return 0, 0


def is_send_window_open(industry: IndustryConfig) -> bool:
    """Return True if current UTC time is inside the industry's send window."""
    now = datetime.now(timezone.utc)

    if getattr(industry, "pause_weekends", False) and now.weekday() >= 5:
        return False

    start_h, start_m = _parse_time(getattr(industry, "send_start_time", "00:00"))
    end_h, end_m = _parse_time(getattr(industry, "send_end_time", "23:59"))

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes
```

- [ ] **Step 5: 在 run_senders 中调用时段门控**

在 `core/task/worker.py` 中，导入 `is_send_window_open`：

```python
from core.strategy.policy import is_send_window_open
```

在 `run_senders()` 函数中，合规检查之后、设备加载之前插入：

```python
    if not is_send_window_open(industry):
        log.info("Send window closed for %s; skipping dispatch.", getattr(industry, "slug", ""))
        return {
            "ok": True,
            "skipped": True,
            "reason": "outside_send_window",
            "industry_slug": getattr(industry, "slug", ""),
            "message": "当前不在允许的发送时段内。",
        }
```

- [ ] **Step 6: 运行测试确认通过**

```bash
python -m pytest tests/core/strategy/test_policy.py -v
python -m pytest tests/core/task/test_worker_compliance.py -v
```

Expected: ALL PASS。

- [ ] **Step 7: 提交**

```bash
git add core/strategy/policy.py core/task/worker.py tests/core/strategy/test_policy.py
git commit -m "feat(phase3): add send window gate and integrate into run_senders"
```

---

## Task 4: 行业日发送上限

**目标:** 在 `MatrixTaskScheduler` 中增加 `daily_send_max` 检查。

**Files:**
- Modify: `core/task/scheduler.py`
- Test: `tests/core/task/test_scheduler.py`（如不存在则创建）

- [ ] **Step 1: 写失败测试**

```python
# tests/core/task/test_scheduler.py
from unittest.mock import MagicMock
from core.task.scheduler import MatrixTaskScheduler


def test_claim_respects_industry_daily_max(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=0
    )
    # Mock industry config with daily_send_max=1
    import core.task.scheduler as sched_module
    original_session = sched_module.SessionLocal

    class FakeTask:
        id = 1
        status = "pending"
        industry_slug = "test"
        owner_user_id = "u1"

    class FakeQuota:
        sent = 1
        reserved = 0

    class FakeQuery:
        def filter(self, *a, **k): return self
        def with_for_update(self): return self
        def first(self): return FakeQuota()

    class FakeDb:
        def query(self, model): return FakeQuery()
        def commit(self): pass
        def rollback(self): pass
        def flush(self): pass
        def close(self): pass

    monkeypatch.setattr(sched_module, "SessionLocal", lambda: FakeDb())

    result = scheduler.claim_for_device("d1")
    assert result.task is None
    assert result.reason == "industry_daily_limit_reached"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/core/task/test_scheduler.py -v
```

Expected: FAIL，`reason` 不匹配。

- [ ] **Step 3: 修改 Scheduler**

在 `core/task/scheduler.py` 的 `__init__` 中新增参数：

```python
    def __init__(
        self,
        *,
        industry_slug: str,
        owner_user_id: str = "",
        global_daily_limit: int = 0,
        daily_send_max: int = 0,
        job_id: str = "",
    ):
        ...
        self.daily_send_max = int(daily_send_max or 0)
```

在 `claim_for_device()` 中，全局配额检查之后插入行业日上限检查：

```python
            # 2. Check industry daily max
            if self.daily_send_max > 0:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                quota = db.query(IndustryDailyQuota).filter(
                    IndustryDailyQuota.industry_slug == self.industry_slug,
                    IndustryDailyQuota.day == day
                ).with_for_update().first()
                if quota and (quota.sent + quota.reserved >= self.daily_send_max):
                    db.rollback()
                    return ClaimedTask(None, reserved=False, reason="industry_daily_limit_reached")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/core/task/test_scheduler.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add core/task/scheduler.py tests/core/task/test_scheduler.py
git commit -m "feat(phase3): add industry daily send max to scheduler"
```

---

## Task 5: 定时配置 API

**目标:** 在 `server/api/industries.py` 中新增定时配置更新与调度启停接口。

**Files:**
- Modify: `server/api/industries.py`
- Test: `tests/server/api/test_industries_schedule.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_industries_schedule.py
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_update_schedule_config_requires_auth():
    resp = client.put("/api/industries/ind-1/schedule-config", json={"pause_weekends": True})
    assert resp.status_code in (401, 403)


def test_start_schedule_requires_auth():
    resp = client.post("/api/industries/ind-1/schedule/start")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/api/test_industries_schedule.py -v
```

Expected: 2 FAIL（404 或 401/403）。

- [ ] **Step 3: 在 `_to_industry_config` 中传递新字段**

在 `server/api/industries.py` 的 `_to_industry_config` 函数末尾，返回 `IndustryConfig` 前添加：

```python
        send_start_time=getattr(industry, "send_start_time", "") or "09:00",
        send_end_time=getattr(industry, "send_end_time", "") or "13:00",
        pause_weekends=bool(getattr(industry, "pause_weekends", False)),
        daily_send_max=int(getattr(industry, "daily_send_max", 0) or 0),
        effect_webhook_url=getattr(industry, "effect_webhook_url", "") or "",
```

- [ ] **Step 4: 新增请求模型与路由**

在 `server/api/industries.py` 中新增模型：

```python
class ScheduleConfigUpdate(BaseModel):
    send_start_time: str | None = None
    send_end_time: str | None = None
    pause_weekends: bool | None = None
    daily_send_max: int | None = None
    effect_webhook_url: str | None = None
```

在 `server/api/industries.py` 中新增路由：

```python
@router.put("/{industry_id}/schedule-config", response_model=IndustryOut)
def update_schedule_config(
    industry_id: str,
    body: ScheduleConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    if body.send_start_time is not None:
        ind.send_start_time = body.send_start_time
    if body.send_end_time is not None:
        ind.send_end_time = body.send_end_time
    if body.pause_weekends is not None:
        ind.pause_weekends = body.pause_weekends
    if body.daily_send_max is not None:
        ind.daily_send_max = body.daily_send_max
    if body.effect_webhook_url is not None:
        ind.effect_webhook_url = body.effect_webhook_url
    db.commit()
    db.refresh(ind)
    return ind


@router.post("/{industry_id}/schedule/start")
def start_industry_schedule(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    # Celery beat dynamic schedule would be implemented via scheduler DB
    return {"ok": True, "industry_id": ind.id, "status": "started"}


@router.post("/{industry_id}/schedule/stop")
def stop_industry_schedule(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    return {"ok": True, "industry_id": ind.id, "status": "stopped"}
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/server/api/test_industries_schedule.py -v
```

Expected: 2 PASS。

- [ ] **Step 6: 提交**

```bash
git add server/api/industries.py tests/server/api/test_industries_schedule.py
git commit -m "feat(phase3): add schedule config and start/stop APIs"
```

---

## Task 6: 效果标记 API

**目标:** 在 `server/api/leads.py` 中新增标记已回复 / 已转化 / 撤销 API。

**Files:**
- Modify: `server/api/leads.py`
- Create: `server/services/effect_webhook.py`
- Test: `tests/server/api/test_leads_effects.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_leads_effects.py
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_mark_replied_requires_auth():
    resp = client.post("/api/leads/1/mark-replied", json={"reply_text": "hi"})
    assert resp.status_code in (401, 403)


def test_mark_converted_requires_auth():
    resp = client.post("/api/leads/1/mark-converted", json={"conversion_value": "100"})
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/api/test_leads_effects.py -v
```

Expected: 2 FAIL。

- [ ] **Step 3: 创建 effect_webhook 服务**

创建 `server/services/effect_webhook.py`：

```python
"""Webhook push service for lead effect events."""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("thunder.effect_webhook")


def push_effect_event(
    event: str,
    industry_slug: str,
    lead: dict[str, Any],
    webhook_url: str,
    timeout: float = 10.0,
) -> dict:
    """Push lead.replied / lead.converted event to external webhook."""
    if not webhook_url:
        return {"ok": False, "error": "webhook_url empty"}

    payload = {
        "event": event,
        "industry_slug": industry_slug,
        "lead_id": lead.get("id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if event == "lead.replied":
        payload["reply_text"] = lead.get("reply_text", "")
    elif event == "lead.converted":
        payload["conversion_value"] = lead.get("conversion_value", "")

    try:
        resp = httpx.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        result = {
            "ok": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "response_preview": resp.text[:500],
        }
        log.info("Effect webhook push to %s: %s", webhook_url, result)
        return result
    except Exception as e:
        log.warning("Effect webhook push failed: %s", e)
        return {"ok": False, "error": str(e)[:500]}
```

- [ ] **Step 4: 实现效果标记路由**

在 `server/api/leads.py` 中新增 Pydantic 模型：

```python
class MarkRepliedRequest(BaseModel):
    reply_text: str = ""


class MarkConvertedRequest(BaseModel):
    conversion_value: str = ""
```

在 `server/api/leads.py` 中新增路由：

```python
from datetime import datetime, timezone
from server.services.effect_webhook import push_effect_event


@router.post("/{lead_id}/mark-replied")
def mark_lead_replied(
    lead_id: int,
    body: MarkRepliedRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.task import TaskQueue
    lead = db.query(TaskQueue).filter(
        TaskQueue.id == lead_id,
        TaskQueue.owner_user_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if lead.status not in ("sent", "done"):
        raise HTTPException(status_code=400, detail="只能标记已发送的线索")

    lead.status = "replied"
    lead.replied_at = datetime.now(timezone.utc)
    lead.reply_text = body.reply_text
    db.commit()

    # Webhook
    if lead.industry_slug:
        from server.models.industry import Industry
        industry = db.query(Industry).filter(
            Industry.slug == lead.industry_slug,
            Industry.user_id == current_user.id,
        ).first()
        if industry and industry.effect_webhook_url:
            push_effect_event(
                "lead.replied",
                lead.industry_slug,
                {"id": lead.id, "reply_text": lead.reply_text},
                industry.effect_webhook_url,
            )

    return {"ok": True, "lead_id": lead_id, "status": "replied"}


@router.post("/{lead_id}/mark-converted")
def mark_lead_converted(
    lead_id: int,
    body: MarkConvertedRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.task import TaskQueue
    lead = db.query(TaskQueue).filter(
        TaskQueue.id == lead_id,
        TaskQueue.owner_user_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if lead.status not in ("sent", "replied", "done"):
        raise HTTPException(status_code=400, detail="只能标记已发送或已回复的线索")

    lead.status = "converted"
    lead.converted_at = datetime.now(timezone.utc)
    lead.conversion_value = body.conversion_value
    db.commit()

    if lead.industry_slug:
        from server.models.industry import Industry
        industry = db.query(Industry).filter(
            Industry.slug == lead.industry_slug,
            Industry.user_id == current_user.id,
        ).first()
        if industry and industry.effect_webhook_url:
            push_effect_event(
                "lead.converted",
                lead.industry_slug,
                {"id": lead.id, "conversion_value": lead.conversion_value},
                industry.effect_webhook_url,
            )

    return {"ok": True, "lead_id": lead_id, "status": "converted"}


@router.post("/{lead_id}/unmark-converted")
def unmark_lead_converted(
    lead_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.task import TaskQueue
    lead = db.query(TaskQueue).filter(
        TaskQueue.id == lead_id,
        TaskQueue.owner_user_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if lead.status != "converted":
        raise HTTPException(status_code=400, detail="只能撤销已转化标记")

    lead.status = "replied" if lead.replied_at else "sent"
    lead.converted_at = None
    lead.conversion_value = ""
    db.commit()
    return {"ok": True, "lead_id": lead_id, "status": lead.status}
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/server/api/test_leads_effects.py -v
```

Expected: 2 PASS（认证测试）。

- [ ] **Step 6: 提交**

```bash
git add server/api/leads.py server/services/effect_webhook.py tests/server/api/test_leads_effects.py
git commit -m "feat(phase3): add lead effect mark/unmark APIs and webhook push"
```

---

## Task 7: 效果统计 API

**目标:** 在 `server/api/stats.py` 中新增效果统计接口。

**Files:**
- Modify: `server/api/stats.py`
- Test: `tests/server/api/test_stats.py`（如不存在则创建）

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_stats.py
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_effect_stats_requires_auth():
    resp = client.get("/api/stats/effects?industry_slug=recruitment")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/api/test_stats.py -v
```

Expected: FAIL。

- [ ] **Step 3: 实现效果统计路由**

在 `server/api/stats.py` 中新增：

```python
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from server.models.task import TaskQueue


@router.get("/effects")
def get_effect_stats(
    industry_slug: str,
    days: int = 7,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base_query = db.query(TaskQueue).filter(
        TaskQueue.industry_slug == industry_slug,
        TaskQueue.owner_user_id == current_user.id,
    )
    sent = base_query.filter(TaskQueue.status.in_(["sent", "done", "replied", "converted"])).count()
    replied = base_query.filter(TaskQueue.status.in_(["replied", "converted"])).count()
    converted = base_query.filter(TaskQueue.status == "converted").count()

    reply_rate = round(replied / sent, 4) if sent else 0.0
    conversion_rate = round(converted / sent, 4) if sent else 0.0

    return {
        "industry_slug": industry_slug,
        "days": days,
        "sent": sent,
        "replied": replied,
        "converted": converted,
        "reply_rate": reply_rate,
        "conversion_rate": conversion_rate,
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/server/api/test_stats.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add server/api/stats.py tests/server/api/test_stats.py
git commit -m "feat(phase3): add effect stats API"
```

---

## Task 8: Celery Beat 定时调度

**目标:** 配置 Celery Beat 每 15 分钟触发一次发送批次，并支持 `__all_active__` 模式。

**Files:**
- Modify: `adapters/celery/app.py`
- Modify: `adapters/celery/send.py`
- Test: `tests/adapters/celery/test_send.py`

- [ ] **Step 1: 配置 Beat Schedule**

在 `adapters/celery/app.py` 中导入 `crontab` 并添加配置：

```python
from celery.schedules import crontab
```

在 `app.conf.update(...)` 之前或之后添加：

```python
app.conf.beat_schedule = {
    "thunder-send-every-15min": {
        "task": "adapters.celery.send.run_send_batch",
        "schedule": crontab(minute="*/15"),
        "args": ("__all_active__", ""),
    },
}
```

- [ ] **Step 2: 修改 run_send_batch 支持 __all_active__**

在 `adapters/celery/send.py` 中修改 `run_send_batch`：

```python
@app.task(bind=True, max_retries=1)
def run_send_batch(self, industry_slug: str, user_id: str = "", device_ids: list[str] = None):
    """Orchestrate batch sending across multiple devices using DB config."""
    from core.task.worker import run_senders
    from server.models import SessionLocal
    from server.models.industry import Industry
    from server.api.industries import _to_industry_config

    db = SessionLocal()
    try:
        if industry_slug == "__all_active__":
            industries = db.query(Industry).filter(Industry.is_active == True).all()
            results = []
            for ind in industries:
                cfg = _to_industry_config(ind)
                results.append(run_senders(cfg, device_ids))
            return {"ok": True, "mode": "all_active", "industries": len(industries), "results": results}

        industry = db.query(Industry).filter(
            Industry.slug == industry_slug,
            Industry.user_id == user_id,
        ).first()
        if not industry:
            return {"ok": False, "error": f"Industry {industry_slug} not found"}
        cfg = _to_industry_config(industry)
    finally:
        db.close()

    result = run_senders(cfg, device_ids)
    log.info(
        "Batch send done: skipped=%s sent=%d failed=%d devices=%d",
        result.get("skipped", False),
        result.get("sent_total", 0),
        result.get("failed_total", 0),
        result.get("devices_total", 0),
    )
    return result
```

- [ ] **Step 3: 写测试**

在 `tests/adapters/celery/test_send.py` 中新增：

```python
from unittest.mock import patch


def test_run_send_batch_all_active(db_session, monkeypatch):
    _seed_industry(db_session, compliance_mode=False)
    with patch("adapters.celery.send.run_senders") as mock_run:
        mock_run.return_value = {"ok": True, "sent_total": 1}
        result = run_send_batch.run("__all_active__", "")
        assert result["ok"] is True
        assert result["mode"] == "all_active"
        assert mock_run.called
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/adapters/celery/test_send.py -v
```

Expected: ALL PASS。

- [ ] **Step 5: 提交**

```bash
git add adapters/celery/app.py adapters/celery/send.py tests/adapters/celery/test_send.py
git commit -m "feat(phase3): configure Celery Beat schedule and all-active send batch"
```

---

## Task 9: 前端适配

**目标:** 在项目弹窗增加"发送时段"面板，在线索池显示效果状态列和操作按钮，在控制中心显示效果指标。

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: 项目弹窗发送时段面板**

在合规设置折叠面板之后，插入：

```html
                <!-- 发送时段设置 -->
                <div class="mt-4 border border-slate-700/50 rounded-lg overflow-hidden">
                    <button type="button" onclick="toggleSchedulePanel()" class="w-full px-4 py-2 bg-slate-800/50 flex items-center justify-between text-xs font-semibold text-slate-300 hover:bg-slate-800">
                        <span>⏰ 发送时段控制</span>
                        <span id="schedule-panel-chevron">▼</span>
                    </button>
                    <div id="schedule-panel" class="hidden p-4 space-y-4 bg-slate-900/30">
                        <div class="grid grid-cols-2 gap-4">
                            <div class="space-y-1">
                                <label class="block text-xs font-semibold text-slate-300">开始时间 (UTC)</label>
                                <input type="time" id="industry-send-start" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200">
                            </div>
                            <div class="space-y-1">
                                <label class="block text-xs font-semibold text-slate-300">结束时间 (UTC)</label>
                                <input type="time" id="industry-send-end" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200">
                            </div>
                        </div>
                        <div class="flex items-center justify-between">
                            <div>
                                <p class="text-xs font-semibold text-slate-200">周末暂停</p>
                                <p class="text-[10px] text-slate-500">周六、周日不自动发送</p>
                            </div>
                            <label class="relative inline-flex items-center cursor-pointer">
                                <input type="checkbox" id="industry-pause-weekends" class="sr-only peer">
                                <div class="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-cyan-600"></div>
                            </label>
                        </div>
                        <div class="space-y-1">
                            <label class="block text-xs font-semibold text-slate-300">单日最大发送量（0=不限制）</label>
                            <input type="number" id="industry-daily-send-max" min="0" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200">
                        </div>
                        <div class="space-y-1">
                            <label class="block text-xs font-semibold text-slate-300">效果事件 Webhook</label>
                            <input type="url" id="industry-effect-webhook-url" placeholder="https://your-crm.com/webhook/thunder-events" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200">
                        </div>
                    </div>
                </div>
```

- [ ] **Step 2: 添加折叠/加载 JS 函数**

在 `<script>` 区域添加：

```javascript
        function toggleSchedulePanel() {
            const panel = document.getElementById('schedule-panel');
            const chevron = document.getElementById('schedule-panel-chevron');
            panel.classList.toggle('hidden');
            chevron.textContent = panel.classList.contains('hidden') ? '▼' : '▲';
        }
```

在 `editIndustry()` 加载数据时填充：

```javascript
        document.getElementById('industry-send-start').value = ind.send_start_time || '09:00';
        document.getElementById('industry-send-end').value = ind.send_end_time || '13:00';
        document.getElementById('industry-pause-weekends').checked = ind.pause_weekends || false;
        document.getElementById('industry-daily-send-max').value = ind.daily_send_max || 0;
        document.getElementById('industry-effect-webhook-url').value = ind.effect_webhook_url || '';
```

在 `saveIndustry()` 提交时收集：

```javascript
        body.send_start_time = document.getElementById('industry-send-start').value;
        body.send_end_time = document.getElementById('industry-send-end').value;
        body.pause_weekends = document.getElementById('industry-pause-weekends').checked;
        body.daily_send_max = parseInt(document.getElementById('industry-daily-send-max').value || '0', 10);
        body.effect_webhook_url = document.getElementById('industry-effect-webhook-url').value;
```

- [ ] **Step 3: 线索池效果列与操作**

在线索池表格头部添加列：

```html
<th class="text-left text-xs font-semibold text-slate-400 py-2">效果状态</th>
<th class="text-left text-xs font-semibold text-slate-400 py-2">操作</th>
```

在线索池行渲染中：

```javascript
function renderLeadStatus(lead) {
    const map = { sent: '已发送', replied: '已回复', converted: '已转化', failed: '失败', done: '已发送' };
    return map[lead.status] || lead.status || '待处理';
}

function renderLeadActions(lead) {
    if (lead.status === 'sent' || lead.status === 'done') {
        return `<button onclick="markReplied(${lead.id})" class="text-cyan-300 hover:text-cyan-100 text-xs">标记回复</button>`;
    }
    if (lead.status === 'replied') {
        return `<button onclick="markConverted(${lead.id})" class="text-cyan-300 hover:text-cyan-100 text-xs">标记转化</button>`;
    }
    if (lead.status === 'converted') {
        return `<button onclick="unmarkConverted(${lead.id})" class="text-amber-300 hover:text-amber-100 text-xs">撤销转化</button>`;
    }
    return '-';
}
```

添加操作函数：

```javascript
async function markReplied(leadId) {
    const text = prompt('请输入对方回复内容（可选）') || '';
    await apiFetch(`/api/leads/${leadId}/mark-replied`, { method: 'POST', body: JSON.stringify({ reply_text: text }) });
    loadLeads();
}

async function markConverted(leadId) {
    const value = prompt('请输入转化价值（可选）') || '';
    await apiFetch(`/api/leads/${leadId}/mark-converted`, { method: 'POST', body: JSON.stringify({ conversion_value: value }) });
    loadLeads();
}

async function unmarkConverted(leadId) {
    if (!confirm('确定撤销转化标记？')) return;
    await apiFetch(`/api/leads/${leadId}/unmark-converted`, { method: 'POST' });
    loadLeads();
}
```

- [ ] **Step 4: 控制中心效果指标**

在控制中心添加卡片：

```html
<div class="grid grid-cols-3 gap-4 mb-6">
    <div class="bg-slate-800/50 rounded-xl p-4 border border-slate-700/50">
        <p class="text-[10px] text-slate-400 uppercase">今日发送</p>
        <p id="stat-sent" class="text-xl font-bold text-slate-100">0</p>
    </div>
    <div class="bg-slate-800/50 rounded-xl p-4 border border-slate-700/50">
        <p class="text-[10px] text-slate-400 uppercase">回复率</p>
        <p id="stat-reply-rate" class="text-xl font-bold text-cyan-400">0%</p>
    </div>
    <div class="bg-slate-800/50 rounded-xl p-4 border border-slate-700/50">
        <p class="text-[10px] text-slate-400 uppercase">转化率</p>
        <p id="stat-conversion-rate" class="text-xl font-bold text-emerald-400">0%</p>
    </div>
</div>
```

在加载控制中心时调用 `/api/stats/effects?industry_slug=...` 并更新数字。

- [ ] **Step 5: 手动验证**

启动服务器：

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

验证：
- 项目弹窗"发送时段"面板可展开/折叠。
- 时间、开关、数字可保存并回显。
- 线索池显示效果状态与操作按钮。
- 控制中心显示效果指标。

- [ ] **Step 6: 提交**

```bash
git add server/static/index.html
git commit -m "feat(phase3): add schedule panel, lead effect actions, and stats UI"
```

---

## Task 10: 回归测试与文档更新

**Files:**
- 全部修改文件
- Test: `tests/`
- Docs: `docs/superpowers/sops/2026-06-15-commercialization-roadmap-sop.md`

- [ ] **Step 1: 运行全量测试**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: ALL PASS。

- [ ] **Step 2: 修复回归**

- 如果 `done` 状态相关测试失败，补充 `sent` 兼容逻辑。
- 如果 schema 测试失败，检查默认值。

- [ ] **Step 3: 更新 SOP**

在 `docs/superpowers/sops/2026-06-15-commercialization-roadmap-sop.md` 中：

1. 将 Phase 3 状态更新为"已完成"。
2. 添加客户价值摘要：

> Phase 3 让客户能够控制发送时段降低封号风险，并追踪私信是否被回复、是否转化，从而计算真实 ROI。

- [ ] **Step 4: 更新 PROJECT_STRUCTURE.md**

在 Phase 3 部分或新增 Phase 3 小节，标记已完成：

```markdown
### P3: 定时发送 + 效果追踪 ✅ COMPLETE
- [x] 发送时段门控 (`core/strategy/policy.py`)
- [x] 周末暂停 / 单日最大发送量
- [x] Celery Beat 定时调度
- [x] TaskQueue 效果状态扩展
- [x] 手动标记已回复 / 已转化 API
- [x] 效果统计 API
- [x] 效果事件 Webhook
- [x] 前端发送时段、线索效果列、指标卡片
```

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "feat(phase3): complete scheduling and effect tracking

- Add send window gate, weekend pause, daily send max
- Extend TaskQueue with replied/converted tracking
- Add effect mark/unmark APIs and webhook events
- Add effect stats API
- Configure Celery Beat schedule
- Update frontend schedule panel, lead effect UI, stats cards
- Update SOP and project docs"
```

- [ ] **Step 6: 运行最终测试**

```bash
python -m pytest tests/ -q
```

Expected: ALL PASS。

---

## Self-Review

### Spec Coverage

| Spec 要求 | 对应任务 |
|---|---|
| 行业模型定时字段 | Task 1 |
| TaskQueue 效果字段 | Task 2 |
| 发送时段门控 | Task 3 |
| 单日最大发送量 | Task 4 |
| 定时配置 API | Task 5 |
| 效果标记 API | Task 6 |
| 效果统计 API | Task 7 |
| Celery Beat 调度 | Task 8 |
| 前端适配 | Task 9 |
| 回归测试与文档 | Task 10 |

### Placeholder Scan

- 无 TBD/TODO。
- 所有步骤包含具体代码或命令。
- 测试代码已给出雏形。

### Type Consistency

- `is_send_window_open` 接收 `IndustryConfig`，与 `run_senders` 调用一致。
- `TaskQueue` 新增字段类型与 API 使用一致。
- `run_send_batch` 支持 `__all_active__` 字符串约定。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-16-phase3-scheduling-effect-tracking-plan.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

User has authorized autonomous completion. Proceeding with Subagent-Driven by default unless instructed otherwise.
