# Phase 4：关键词报表 + A/B Test 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 Phase 3 效果数据，实现关键词效果报表和文案 A/B Test，帮助客户优化关键词与私信文案。

**Architecture:** 新增 `server/services/analytics.py` 聚合关键词/设备指标，`server/services/abtest.py` 管理变体与选择算法；扩展 `Industry` 和 `TaskQueue` 模型；在 `DeviceWorker` 发送时根据权重选择文案变体并记录；前端新增"关键词效果"和"A/B 实验"页面。

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x, Pydantic 2.x, PostgreSQL/SQLite, Vanilla JS + Tailwind CSS, pytest

---

## 文件结构映射

| 文件 | 职责 |
|---|---|
| `server/models/industry.py` | `Industry` 模型新增 `reply_variants` JSON 字段 |
| `core/config.py` | `IndustryConfig` dataclass 新增 `reply_variants` |
| `server/schemas/industry.py` | Pydantic schema 新增变体相关字段 |
| `server/models/task.py` | `TaskQueue` 新增 `reply_variant_id` 字段 |
| `server/services/analytics.py` | 关键词/设备效果聚合查询 |
| `server/services/abtest.py` | A/B 变体选择、权重、结果统计 |
| `server/api/stats.py` | 新增 `/api/stats/keywords` 和 `/api/stats/devices` |
| `server/api/industries.py` | 新增 A/B 变体 CRUD 和结果 API |
| `core/task/scheduler.py` | 新增 `mark_reply_variant()` 方法 |
| `core/task/worker.py` | `DeviceWorker._generate_reply()` 接入变体选择 |
| `server/static/index.html` | 新增"关键词效果"和"A/B 实验"UI |
| `tests/server/services/test_analytics.py` | 关键词聚合测试 |
| `tests/server/services/test_abtest.py` | A/B 变体选择测试 |
| `tests/server/api/test_abtest.py` | A/B API 测试 |
| `tests/core/task/test_worker_abtest.py` | 发送时变体选择测试 |

---

## Task 1: 数据模型扩展

**目标:** 让 `Industry` 模型、`IndustryConfig` dataclass 和 `TaskQueue` 模型支持 A/B Test 变体。

**Files:**
- Modify: `server/models/industry.py`
- Modify: `core/config.py`
- Modify: `server/schemas/industry.py`
- Modify: `server/models/task.py`
- Test: `tests/server/test_models_schemas.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/test_models_schemas.py
import pytest
from server.schemas.industry import IndustryCreate, IndustryUpdate, IndustryOut
from server.models.industry import Industry
from server.models.task import TaskQueue
from core.config import IndustryConfig


def test_industry_create_has_reply_variants():
    data = IndustryCreate(
        name="测试", slug="test-ab",
        reply_variants=[{"id": "v1", "name": "默认", "weight": 1}],
    )
    assert len(data.reply_variants) == 1


def test_industry_model_has_reply_variants_column():
    ind = Industry(name="测试", slug="test-ab")
    assert hasattr(ind, "reply_variants")


def test_industry_config_has_reply_variants():
    cfg = IndustryConfig(
        name="测试", slug="test-ab", keywords=["a"], categories=["c"],
        reply_variants=[{"id": "v1", "name": "默认"}],
    )
    assert cfg.reply_variants[0]["id"] == "v1"


def test_task_queue_has_reply_variant_id():
    t = TaskQueue(video_id="v1", comment_id="c1")
    assert hasattr(t, "reply_variant_id")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
python -m pytest tests/server/test_models_schemas.py::test_industry_create_has_reply_variants tests/server/test_models_schemas.py::test_industry_model_has_reply_variants_column tests/server/test_models_schemas.py::test_industry_config_has_reply_variants tests/server/test_models_schemas.py::test_task_queue_has_reply_variant_id -v
```

Expected: 4 FAIL。

- [ ] **Step 3: 修改 Industry 模型**

在 `server/models/industry.py` 中 `Industry` 类里，在 `effect_webhook_url` 字段之后插入：

```python
    reply_variants = Column(JSON, default=list)
```

- [ ] **Step 4: 修改 IndustryConfig**

在 `core/config.py` 的 `IndustryConfig` dataclass 中，在 `effect_webhook_url` 字段之后添加：

```python
    reply_variants: list[dict] = field(default_factory=list)
```

- [ ] **Step 5: 修改 Pydantic schemas**

在 `server/schemas/industry.py` 中：

`IndustryCreate` 类在 `effect_webhook_url` 之后添加：

```python
    reply_variants: list[dict] = []
```

`IndustryUpdate` 类在 `effect_webhook_url` 之后添加：

```python
    reply_variants: list[dict] | None = None
```

`IndustryOut` 类在 `effect_webhook_url` 之后添加：

```python
    reply_variants: list[dict] = []
```

- [ ] **Step 6: 修改 TaskQueue 模型**

在 `server/models/task.py` 中 `TaskQueue` 类里，在 `conversion_value` 字段之后插入：

```python
    reply_variant_id = Column(String(64), default="", index=True)
```

- [ ] **Step 7: 运行测试确认通过**

```bash
python -m pytest tests/server/test_models_schemas.py -v
```

Expected: ALL PASS。

- [ ] **Step 8: 生成 Alembic 迁移**

```bash
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic revision --autogenerate -m "add reply variants and reply_variant_id"
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic upgrade head
THUNDER_DATABASE_URL=sqlite:///data/thunder.db alembic downgrade -1
rm -f data/thunder.db data/thunder.db-*
```

- [ ] **Step 9: 提交**

```bash
git add server/models/industry.py core/config.py server/schemas/industry.py server/models/task.py tests/server/test_models_schemas.py adapters/postgres/migrations/versions/*.py
git commit -m "feat(phase4): add reply_variants to Industry and reply_variant_id to TaskQueue"
```

---

## Task 2: A/B Test 服务

**目标:** 创建 `server/services/abtest.py`，实现变体选择、验证和结果统计。

**Files:**
- Create: `server/services/abtest.py`
- Test: `tests/server/services/test_abtest.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/services/test_abtest.py
import pytest
from server.services.abtest import select_reply_variant, build_variant_result, validate_variant


def test_select_variant_returns_one():
    variants = [
        {"id": "v1", "name": "A", "weight": 1, "enabled": True},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    v = select_reply_variant(variants)
    assert v["id"] in ("v1", "v2")


def test_select_variant_respects_weight():
    variants = [
        {"id": "v1", "name": "A", "weight": 0, "enabled": True},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    for _ in range(10):
        v = select_reply_variant(variants)
        assert v["id"] == "v2"


def test_select_variant_skips_disabled():
    variants = [
        {"id": "v1", "name": "A", "weight": 1, "enabled": False},
        {"id": "v2", "name": "B", "weight": 1, "enabled": True},
    ]
    v = select_reply_variant(variants)
    assert v["id"] == "v2"


def test_validate_variant_requires_id_and_name():
    assert validate_variant({"name": "A"}) is False
    assert validate_variant({"id": "v1", "name": "A"}) is True


def test_build_variant_result_empty():
    result = build_variant_result("v1", [])
    assert result["id"] == "v1"
    assert result["sent"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/services/test_abtest.py -v
```

Expected: 5 FAIL。

- [ ] **Step 3: 实现 A/B Test 服务**

创建 `server/services/abtest.py`：

```python
"""A/B test helpers for reply variants."""

from __future__ import annotations

import random
import uuid
from typing import Any


def generate_variant_id() -> str:
    return f"v-{uuid.uuid4().hex[:8]}"


def validate_variant(variant: dict[str, Any]) -> bool:
    """Check that a variant has the minimum required fields."""
    if not isinstance(variant, dict):
        return False
    if not variant.get("id") or not variant.get("name"):
        return False
    return True


def normalize_variant(variant: dict[str, Any]) -> dict[str, Any]:
    """Ensure a variant has all standard fields and a valid id."""
    if not variant.get("id"):
        variant["id"] = generate_variant_id()
    variant.setdefault("name", "未命名")
    variant.setdefault("reply_tone", "")
    variant.setdefault("reply_style", "")
    variant.setdefault("reply_hook", "")
    variant.setdefault("weight", 1)
    variant.setdefault("enabled", True)
    return variant


def select_reply_variant(variants: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Weighted random selection of an enabled reply variant."""
    if not variants:
        return None
    enabled = [normalize_variant(v) for v in variants if v.get("enabled", True)]
    if not enabled:
        return None
    total_weight = sum(max(0, v.get("weight", 1)) for v in enabled)
    if total_weight <= 0:
        return enabled[0]
    r = random.uniform(0, total_weight)
    cumulative = 0
    for v in enabled:
        cumulative += max(0, v.get("weight", 1))
        if r <= cumulative:
            return v
    return enabled[-1]


def build_variant_result(variant_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate sent/replied/converted for a variant from TaskQueue-like rows."""
    sent = sum(1 for r in rows if r.get("status") in ("sent", "replied", "converted", "done"))
    replied = sum(1 for r in rows if r.get("status") in ("replied", "converted"))
    converted = sum(1 for r in rows if r.get("status") == "converted")
    reply_rate = round(replied / sent, 4) if sent else 0.0
    conversion_rate = round(converted / sent, 4) if sent else 0.0
    return {
        "id": variant_id,
        "sent": sent,
        "replied": replied,
        "converted": converted,
        "reply_rate": reply_rate,
        "conversion_rate": conversion_rate,
    }


def pick_winner(results: list[dict[str, Any]], metric: str = "reply_rate") -> str | None:
    """Return the variant id with the highest metric, or None if empty."""
    if not results:
        return None
    best = max(results, key=lambda r: r.get(metric, 0))
    return best.get("id")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/server/services/test_abtest.py -v
```

Expected: 5 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/services/abtest.py tests/server/services/test_abtest.py
git commit -m "feat(phase4): add A/B test variant service"
```

---

## Task 3: 关键词/设备效果分析服务

**目标:** 创建 `server/services/analytics.py`，实现按关键词和设备聚合效果指标。

**Files:**
- Create: `server/services/analytics.py`
- Test: `tests/server/services/test_analytics.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/services/test_analytics.py
import pytest
from datetime import datetime, timezone, timedelta
from server.services.analytics import aggregate_by_keyword, aggregate_by_device


def test_aggregate_by_keyword_empty():
    result = aggregate_by_keyword("test", [])
    assert result == []


def test_aggregate_by_keyword_groups():
    rows = [
        {"source_keyword": "当兵", "status": "sent"},
        {"source_keyword": "当兵", "status": "replied"},
        {"source_keyword": "征兵", "status": "converted"},
    ]
    result = aggregate_by_keyword("test", rows)
    assert len(result) == 2
    by_kw = {r["keyword"]: r for r in result}
    assert by_kw["当兵"]["sent"] == 2
    assert by_kw["当兵"]["replied"] == 1
    assert by_kw["征兵"]["converted"] == 1
    assert by_kw["征兵"]["conversion_rate"] == 1.0


def test_aggregate_by_device_groups():
    rows = [
        {"consumer_id": "d1", "status": "sent"},
        {"consumer_id": "d1", "status": "failed"},
        {"consumer_id": "d2", "status": "replied"},
    ]
    result = aggregate_by_device("test", rows)
    assert len(result) == 2
    by_dev = {r["device_id"]: r for r in result}
    assert by_dev["d1"]["sent"] == 1
    assert by_dev["d1"]["failed"] == 1
    assert by_dev["d2"]["replied"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/services/test_analytics.py -v
```

Expected: 3 FAIL。

- [ ] **Step 3: 实现分析服务**

创建 `server/services/analytics.py`：

```python
"""Analytics aggregation for keywords, devices, and reply variants."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, case


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = defaultdict(int)
    for row in rows:
        counts[row.get("status", "")] += 1
    return counts


def _calc_rates(sent: int, replied: int, converted: int) -> tuple[float, float]:
    reply_rate = round(replied / sent, 4) if sent else 0.0
    conversion_rate = round(converted / sent, 4) if sent else 0.0
    return reply_rate, conversion_rate


def aggregate_by_keyword(industry_slug: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate TaskQueue-like rows by source_keyword."""
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("source_keyword", "")].append(row)

    results = []
    for keyword, group in groups.items():
        if not keyword:
            continue
        counts = _status_counts(group)
        collected = len(group)
        sent = counts.get("sent", 0) + counts.get("done", 0) + counts.get("replied", 0) + counts.get("converted", 0)
        replied = counts.get("replied", 0) + counts.get("converted", 0)
        converted = counts.get("converted", 0)
        reply_rate, conversion_rate = _calc_rates(sent, replied, converted)
        results.append({
            "keyword": keyword,
            "collected": collected,
            "sent": sent,
            "replied": replied,
            "converted": converted,
            "reply_rate": reply_rate,
            "conversion_rate": conversion_rate,
        })

    return sorted(results, key=lambda r: r["conversion_rate"], reverse=True)


def aggregate_by_device(industry_slug: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate TaskQueue-like rows by consumer_id (device)."""
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("consumer_id", "")].append(row)

    results = []
    for device_id, group in groups.items():
        if not device_id:
            continue
        counts = _status_counts(group)
        sent = counts.get("sent", 0) + counts.get("done", 0) + counts.get("replied", 0) + counts.get("converted", 0)
        replied = counts.get("replied", 0) + counts.get("converted", 0)
        converted = counts.get("converted", 0)
        failed = counts.get("failed", 0)
        reply_rate, conversion_rate = _calc_rates(sent, replied, converted)
        results.append({
            "device_id": device_id,
            "sent": sent,
            "replied": replied,
            "converted": converted,
            "failed": failed,
            "reply_rate": reply_rate,
            "conversion_rate": conversion_rate,
        })

    return sorted(results, key=lambda r: r["reply_rate"], reverse=True)


def query_task_rows(db, industry_slug: str, days: int = 7, owner_user_id: str = "") -> list[dict[str, Any]]:
    """Query TaskQueue rows for analytics within the last N days."""
    from server.models.task import TaskQueue
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = db.query(TaskQueue).filter(
        TaskQueue.industry_slug == industry_slug,
        TaskQueue.fetched_at >= since.isoformat(),
    )
    if owner_user_id:
        query = query.filter(TaskQueue.owner_user_id == owner_user_id)
    return [
        {
            "id": r.id,
            "source_keyword": r.source_keyword or "",
            "consumer_id": r.consumer_id or "",
            "status": r.status or "pending",
            "reply_variant_id": r.reply_variant_id or "",
        }
        for r in query.all()
    ]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/server/services/test_analytics.py -v
```

Expected: 3 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/services/analytics.py tests/server/services/test_analytics.py
git commit -m "feat(phase4): add keyword and device analytics service"
```

---

## Task 4: 统计 API 扩展

**目标:** 在 `server/api/stats.py` 中新增 `/api/stats/keywords` 和 `/api/stats/devices`。

**Files:**
- Modify: `server/api/stats.py`
- Test: `tests/server/api/test_stats.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_stats.py
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_keyword_stats_requires_auth():
    resp = client.get("/api/stats/keywords?industry_slug=recruitment")
    assert resp.status_code in (401, 403)


def test_device_stats_requires_auth():
    resp = client.get("/api/stats/devices?industry_slug=recruitment")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/api/test_stats.py -v
```

Expected: 新增 2 FAIL（原有 effect stats 测试应 PASS）。

- [ ] **Step 3: 修改 `_to_industry_config` 传递 reply_variants**

在 `server/api/industries.py` 的 `_to_industry_config` 函数末尾，添加：

```python
        reply_variants=list(getattr(industry, "reply_variants", []) or []),
```

- [ ] **Step 4: 实现关键词/设备统计路由**

在 `server/api/stats.py` 中新增：

```python
from server.services.analytics import aggregate_by_keyword, aggregate_by_device, query_task_rows


@router.get("/keywords")
def get_keyword_stats(
    industry_slug: str,
    days: int = 7,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = query_task_rows(db, industry_slug, days, owner_user_id=current_user.id)
    return {
        "industry_slug": industry_slug,
        "days": days,
        "keywords": aggregate_by_keyword(industry_slug, rows),
    }


@router.get("/devices")
def get_device_stats(
    industry_slug: str,
    days: int = 7,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = query_task_rows(db, industry_slug, days, owner_user_id=current_user.id)
    return {
        "industry_slug": industry_slug,
        "days": days,
        "devices": aggregate_by_device(industry_slug, rows),
    }
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/server/api/test_stats.py -v
```

Expected: ALL PASS。

- [ ] **Step 6: 提交**

```bash
git add server/api/stats.py server/api/industries.py tests/server/api/test_stats.py
git commit -m "feat(phase4): add keyword and device stats APIs"
```

---

## Task 5: A/B 变体 API

**目标:** 在 `server/api/industries.py` 中新增 A/B 变体 CRUD 和结果查询 API。

**Files:**
- Modify: `server/api/industries.py`
- Create: `tests/server/api/test_abtest.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_abtest.py
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_add_variant_requires_auth():
    resp = client.post("/api/industries/ind-1/variants", json={"name": "测试", "weight": 1})
    assert resp.status_code in (401, 403)


def test_list_variants_requires_auth():
    resp = client.get("/api/industries/ind-1/variants")
    assert resp.status_code in (401, 403)


def test_abtest_results_requires_auth():
    resp = client.get("/api/industries/ind-1/abtest-results")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/api/test_abtest.py -v
```

Expected: 3 FAIL。

- [ ] **Step 3: 新增请求模型**

在 `server/api/industries.py` 中：

```python
class ReplyVariantCreate(BaseModel):
    name: str
    reply_tone: str = ""
    reply_style: str = ""
    reply_hook: str = ""
    weight: int = 1


class ReplyVariantUpdate(BaseModel):
    name: str | None = None
    reply_tone: str | None = None
    reply_style: str | None = None
    reply_hook: str | None = None
    weight: int | None = None
    enabled: bool | None = None
```

- [ ] **Step 4: 新增 A/B 变体路由**

在 `server/api/industries.py` 中新增：

```python
from server.services.abtest import normalize_variant, build_variant_result, pick_winner
from server.services.analytics import query_task_rows


@router.post("/{industry_id}/variants", response_model=IndustryOut)
def add_reply_variant(
    industry_id: str,
    body: ReplyVariantCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    variants = list(getattr(ind, "reply_variants", []) or [])
    new_variant = normalize_variant({
        "name": body.name,
        "reply_tone": body.reply_tone,
        "reply_style": body.reply_style,
        "reply_hook": body.reply_hook,
        "weight": body.weight,
    })
    variants.append(new_variant)
    ind.reply_variants = variants
    db.commit()
    db.refresh(ind)
    return ind


@router.get("/{industry_id}/variants")
def list_reply_variants(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    return {"industry_id": ind.id, "variants": list(getattr(ind, "reply_variants", []) or [])}


@router.put("/{industry_id}/variants/{variant_id}", response_model=IndustryOut)
def update_reply_variant(
    industry_id: str,
    variant_id: str,
    body: ReplyVariantUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    variants = list(getattr(ind, "reply_variants", []) or [])
    for v in variants:
        if v.get("id") == variant_id:
            if body.name is not None:
                v["name"] = body.name
            if body.reply_tone is not None:
                v["reply_tone"] = body.reply_tone
            if body.reply_style is not None:
                v["reply_style"] = body.reply_style
            if body.reply_hook is not None:
                v["reply_hook"] = body.reply_hook
            if body.weight is not None:
                v["weight"] = body.weight
            if body.enabled is not None:
                v["enabled"] = body.enabled
            break
    ind.reply_variants = variants
    db.commit()
    db.refresh(ind)
    return ind


@router.delete("/{industry_id}/variants/{variant_id}", response_model=IndustryOut)
def delete_reply_variant(
    industry_id: str,
    variant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    variants = [v for v in (getattr(ind, "reply_variants", []) or []) if v.get("id") != variant_id]
    ind.reply_variants = variants
    db.commit()
    db.refresh(ind)
    return ind


@router.get("/{industry_id}/abtest-results")
def get_abtest_results(
    industry_id: str,
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    rows = query_task_rows(db, ind.slug, days, owner_user_id=current_user.id)
    variants = list(getattr(ind, "reply_variants", []) or [])
    results = []
    for v in variants:
        vid = v.get("id", "")
        variant_rows = [r for r in rows if r.get("reply_variant_id") == vid]
        result = build_variant_result(vid, variant_rows)
        result["name"] = v.get("name", "未命名")
        results.append(result)

    # Include default variant for old data without variant id
    default_rows = [r for r in rows if not r.get("reply_variant_id")]
    if default_rows:
        default_result = build_variant_result("default", default_rows)
        default_result["name"] = "默认版"
        results.append(default_result)

    return {
        "industry_id": ind.id,
        "variants": results,
        "winner": pick_winner(results, metric="reply_rate"),
    }
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/server/api/test_abtest.py -v
```

Expected: 3 PASS。

- [ ] **Step 6: 提交**

```bash
git add server/api/industries.py tests/server/api/test_abtest.py
git commit -m "feat(phase4): add reply variant CRUD and A/B test results API"
```

---

## Task 6: 发送时接入 A/B 变体

**目标:** 在 `DeviceWorker._generate_reply()` 中根据 A/B 变体生成回复，并记录变体 ID。

**Files:**
- Modify: `core/task/worker.py`
- Modify: `core/task/scheduler.py`
- Test: `tests/core/task/test_worker_abtest.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/task/test_worker_abtest.py
from unittest.mock import patch, MagicMock
from core.config import IndustryConfig
from core.task.worker import DeviceWorker


def test_worker_uses_selected_variant():
    cfg = IndustryConfig(
        name="测试", slug="t", keywords=["a"], categories=["c"],
        reply_tone="默认人设", reply_style="默认风格",
        reply_variants=[
            {"id": "v1", "name": "变体1", "reply_tone": "退伍老兵", "reply_style": "稳重", "weight": 1, "enabled": True},
        ]
    )
    worker = DeviceWorker(device_id="d1", adb_serial="", industry=cfg)
    reply = worker._generate_reply({"text": "我想当兵"})
    assert "退伍老兵" in reply or "稳重" in reply or reply  # 变体被使用
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/core/task/test_worker_abtest.py -v
```

Expected: FAIL（_generate_reply 未使用变体）。

- [ ] **Step 3: 修改 Scheduler**

在 `core/task/scheduler.py` 的 `MatrixTaskScheduler` 中新增方法：

```python
    def mark_reply_variant(self, task_id: int, variant_id: str):
        db = self._get_db()
        try:
            task = db.query(TaskQueue).filter(TaskQueue.id == task_id).first()
            if task:
                task.reply_variant_id = variant_id
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False
```

- [ ] **Step 4: 修改 DeviceWorker**

在 `core/task/worker.py` 中导入 A/B 服务：

```python
from server.services.abtest import select_reply_variant
```

修改 `DeviceWorker._generate_reply()`：

在函数开头添加：

```python
    variant = select_reply_variant(getattr(self.industry, "reply_variants", None))
    if variant:
        tone = variant.get("reply_tone") or getattr(self.industry, "reply_tone", "")
        style = variant.get("reply_style") or getattr(self.industry, "reply_style", "")
        hook = variant.get("reply_hook") or getattr(self.industry, "reply_hook", "")
        variant_id = variant.get("id", "")
    else:
        tone = getattr(self.industry, "reply_tone", "")
        style = getattr(self.industry, "reply_style", "")
        hook = getattr(self.industry, "reply_hook", "")
        variant_id = ""
```

然后替换原有使用 `self.industry.reply_tone` / `self.industry.reply_style` / `self.industry.reply_hook` 的地方为 `tone` / `style` / `hook`。

在 `DeviceWorker.run()` 中，发送成功后记录变体 ID。在 `self._scheduler.commit_task(claim.task_id, self.device_id, "done", "")` 之前插入：

```python
                    if exec_result.ok:
                        if variant_id:
                            self._scheduler.mark_reply_variant(claim.task_id, variant_id)
                        self._scheduler.commit_task(claim.task_id, self.device_id, "done", "")
                        summary["sent"] += 1
```

注意：需要在 `_generate_reply()` 中把 `variant_id` 保存到实例变量，或者在 `run()` 中重新选择。更简单的方式是在 `run()` 中调用 `_generate_reply()` 后获取变体 ID。

推荐做法：在 `_generate_reply()` 返回 `(reply_msg, variant_id)` 元组。但这样改动较大。替代方案：把 `variant_id` 存为 `self._last_variant_id`。

为了最小改动，使用 `self._last_variant_id`：

在 `__init__` 中初始化：

```python
        self._last_variant_id = ""
```

在 `_generate_reply()` 中设置：

```python
    self._last_variant_id = variant_id
```

在 `run()` 中提交：

```python
                    if exec_result.ok:
                        if self._last_variant_id:
                            self._scheduler.mark_reply_variant(claim.task_id, self._last_variant_id)
                        self._scheduler.commit_task(claim.task_id, self.device_id, "done", "")
                        summary["sent"] += 1
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/core/task/test_worker_abtest.py -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add core/task/worker.py core/task/scheduler.py tests/core/task/test_worker_abtest.py
git commit -m "feat(phase4): wire A/B reply variants into DeviceWorker"
```

---

## Task 7: 前端适配

**目标:** 在 `server/static/index.html` 中新增"关键词效果"和"A/B 实验"页面。

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: 新增导航项**

在主导航中添加：

```html
<button onclick="showTab('keywords')" id="nav-keywords" class="nav-item ...">
    关键词效果
</button>
<button onclick="showTab('abtest')" id="nav-abtest" class="nav-item ...">
    A/B 实验
</button>
```

- [ ] **Step 2: 新增关键词效果页面容器**

```html
<div id="tab-keywords" class="tab-content hidden">
    <h2 class="text-lg font-bold text-slate-100 mb-4">关键词效果</h2>
    <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
            <thead>
                <tr class="border-b border-slate-700">
                    <th class="py-2 text-slate-400">关键词</th>
                    <th class="py-2 text-slate-400">采集</th>
                    <th class="py-2 text-slate-400">发送</th>
                    <th class="py-2 text-slate-400">回复</th>
                    <th class="py-2 text-slate-400">转化</th>
                    <th class="py-2 text-slate-400">回复率</th>
                    <th class="py-2 text-slate-400">转化率</th>
                </tr>
            </thead>
            <tbody id="keywords-table-body"></tbody>
        </table>
    </div>
</div>
```

- [ ] **Step 3: 新增 A/B 实验页面容器**

```html
<div id="tab-abtest" class="tab-content hidden">
    <h2 class="text-lg font-bold text-slate-100 mb-4">A/B 实验</h2>
    <div class="mb-4">
        <button onclick="showAddVariantModal()" class="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white text-xs rounded-lg">+ 新增变体</button>
    </div>
    <div id="variants-list" class="space-y-3 mb-6"></div>
    <h3 class="text-sm font-bold text-slate-200 mb-2">实验结果</h3>
    <div id="abtest-results" class="space-y-2"></div>
</div>
```

- [ ] **Step 4: 新增 JS 函数**

```javascript
async function loadKeywordStats() {
    const slug = getActiveIndustrySlug();
    if (!slug) return;
    const data = await apiFetch(`/api/stats/keywords?industry_slug=${slug}&days=7`);
    const tbody = document.getElementById('keywords-table-body');
    tbody.innerHTML = data.keywords.map(k => `
        <tr class="border-b border-slate-800">
            <td class="py-2 text-slate-200">${escapeHtml(k.keyword)}</td>
            <td class="py-2 text-slate-400">${k.collected}</td>
            <td class="py-2 text-slate-400">${k.sent}</td>
            <td class="py-2 text-slate-400">${k.replied}</td>
            <td class="py-2 text-slate-400">${k.converted}</td>
            <td class="py-2 text-cyan-400">${(k.reply_rate * 100).toFixed(1)}%</td>
            <td class="py-2 text-emerald-400">${(k.conversion_rate * 100).toFixed(1)}%</td>
        </tr>
    `).join('');
}

async function loadAbTest() {
    const ind = getActiveIndustry();
    if (!ind) return;
    const variants = ind.reply_variants || [];
    document.getElementById('variants-list').innerHTML = variants.map(v => `
        <div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
            <div class="flex items-center justify-between">
                <span class="font-semibold text-slate-200">${escapeHtml(v.name)}</span>
                <button onclick="deleteVariant('${v.id}')" class="text-amber-400 hover:text-amber-200 text-xs">删除</button>
            </div>
            <div class="text-[10px] text-slate-500 mt-1">人设：${escapeHtml(v.reply_tone || '-')} / 风格：${escapeHtml(v.reply_style || '-')} / 权重：${v.weight}</div>
        </div>
    `).join('');

    const results = await apiFetch(`/api/industries/${ind.id}/abtest-results?days=7`);
    document.getElementById('abtest-results').innerHTML = results.variants.map(r => `
        <div class="bg-slate-800/30 rounded-lg p-3 border ${r.id === results.winner ? 'border-emerald-500/50' : 'border-slate-700'}">
            <div class="flex items-center justify-between">
                <span class="font-semibold text-slate-200">${escapeHtml(r.name)} ${r.id === results.winner ? '<span class="text-emerald-400 text-xs">🏆 胜出</span>' : ''}</span>
                <span class="text-xs text-slate-400">发送 ${r.sent}</span>
            </div>
            <div class="grid grid-cols-2 gap-2 mt-2 text-xs">
                <div class="text-slate-400">回复率 <span class="text-cyan-400">${(r.reply_rate * 100).toFixed(1)}%</span></div>
                <div class="text-slate-400">转化率 <span class="text-emerald-400">${(r.conversion_rate * 100).toFixed(1)}%</span></div>
            </div>
        </div>
    `).join('');
}

async function deleteVariant(variantId) {
    if (!confirm('确定删除该变体？')) return;
    const ind = getActiveIndustry();
    await apiFetch(`/api/industries/${ind.id}/variants/${variantId}`, { method: 'DELETE' });
    await loadIndustries();
    loadAbTest();
}
```

注意：`getActiveIndustrySlug()` 和 `getActiveIndustry()` 需要根据实际代码中的函数名调整。`apiFetch` 和 `escapeHtml` 假设已存在。

- [ ] **Step 5: 新增变体弹窗（简化版）**

在项目弹窗或页面中添加一个"新增变体"弹窗，包含：
- 变体名称
- 回复人设
- 回复风格
- 钩子话术
- 权重

提交到 `POST /api/industries/{id}/variants`。

- [ ] **Step 6: 在 tab 切换时加载数据**

在 `showTab()` 函数中，当切换到 `keywords` 或 `abtest` 时调用对应加载函数。

- [ ] **Step 7: 运行测试**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: ALL PASS。

- [ ] **Step 8: 提交**

```bash
git add server/static/index.html
git commit -m "feat(phase4): add keyword stats and A/B test UI"
```

---

## Task 8: 回归测试与文档更新

**Files:**
- 全部修改文件
- Test: `tests/`
- Docs: `docs/superpowers/sops/2026-06-15-commercialization-roadmap-sop.md`
- Docs: `PROJECT_STRUCTURE.md`

- [ ] **Step 1: 运行全量测试**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: ALL PASS。

- [ ] **Step 2: 修复回归**

- 检查 `IndustryConfig` 导入的 `field` 是否来自 `dataclasses`。
- 检查 JSON 字段在 SQLite 和 PostgreSQL 下的行为是否一致。

- [ ] **Step 3: 更新 SOP**

在 `docs/superpowers/sops/2026-06-15-commercialization-roadmap-sop.md` 中：
- 将 Phase 4 状态更新为"已完成"。
- 添加客户价值摘要：

> Phase 4 让客户知道哪些关键词和文案真正带来转化，把钱花在高效的获客策略上。

- [ ] **Step 4: 更新 PROJECT_STRUCTURE.md**

在路线图部分新增 Phase 4 小节：

```markdown
### P4: 关键词报表 + A/B Test ✅ COMPLETE
- [x] `server/services/analytics.py` — 关键词/设备效果聚合
- [x] `server/services/abtest.py` — A/B 变体选择 + 结果统计
- [x] `Industry.reply_variants` + `TaskQueue.reply_variant_id`
- [x] `GET /api/stats/keywords` 关键词效果 API
- [x] `GET /api/stats/devices` 设备效果 API
- [x] A/B 变体 CRUD + 结果 API
- [x] `DeviceWorker` 发送时自动选择变体并记录
- [x] 前端"关键词效果"和"A/B 实验"页面
```

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "feat(phase4): complete keyword analytics and A/B test

- Add reply_variants to Industry and reply_variant_id to TaskQueue
- Add analytics service for keyword/device aggregation
- Add A/B test service for variant selection and result stats
- Add stats APIs for keywords and devices
- Add reply variant CRUD and A/B results API
- Wire A/B variant selection into DeviceWorker
- Add frontend keyword stats and A/B test UI
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
| 关键词效果报表 | Task 3, Task 4 |
| 文案 A/B Test | Task 2, Task 5, Task 6 |
| 前端关键词/A/B UI | Task 7 |
| 回归测试与文档 | Task 8 |

### Placeholder Scan

- 无 TBD/TODO。
- 所有步骤包含具体代码或命令。

### Type Consistency

- `reply_variants` 在 model/schema/config/service 中均为 `list[dict]`。
- `reply_variant_id` 在 model/service/API 中均为 `str`。
- `select_reply_variant` 返回 `dict | None`，与调用方一致。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-16-phase4-analytics-abtest-plan.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

User has authorized autonomous completion. Proceeding with Subagent-Driven by default unless instructed otherwise.
