# 阶段 1：数据导出 + 合规模式 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在雷霆捕获系统中实现线索 Excel/CSV 导出、Webhook 推送与项目级合规模式（只采集不发送），且不破坏原有 AI 自动私信能力。

**Architecture:** 在 `sa_industries` 表与 `IndustryConfig` 中新增合规字段；在 `run_senders` 入口做合规拦截；新增独立的 `export` 和 `webhook` 服务模块；前端通过 Vanilla JS 在原 SPA 中增加开关与导出按钮。所有改动以增量方式叠加到现有 FastAPI + SQLAlchemy + Celery 架构上。

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x, Pydantic 2.x, PostgreSQL/SQLite, Vanilla JS, pytest, openpyxl, httpx

---

## 文件结构映射

| 文件 | 职责 |
|---|---|
| `server/models/industry.py` | `Industry` 模型新增合规字段 |
| `core/config.py` | `IndustryConfig` dataclass 新增合规字段 |
| `server/schemas/industry.py` | Pydantic schema 新增字段校验与输出 |
| `server/services/export.py` | 新增：CSV/Excel 线索导出生成器 |
| `server/services/webhook.py` | 新增：线索 Webhook 推送与日志 |
| `server/api/leads.py` | 新增：`POST /api/leads/export` 导出接口 |
| `server/api/industries.py` | 新增：合规配置与 Webhook 测试接口 |
| `core/task/worker.py` | 修改：`run_senders()` 合规模式拦截 |
| `adapters/celery/send.py` | 修改：`run_send_batch` 使用 DB 行业配置 |
| `server/static/index.html` | 修改：项目弹窗、控制中心、线索池 UI |
| `tests/server/api/test_leads.py` | 新增：导出 API 测试 |
| `tests/server/api/test_industries_compliance.py` | 新增：合规配置 API 测试 |
| `tests/server/services/test_export.py` | 新增：导出服务测试 |
| `tests/server/services/test_webhook.py` | 新增：Webhook 服务测试 |
| `tests/core/task/test_worker_compliance.py` | 新增：发送入口合规拦截测试 |

---

## Task 1: 数据库模型与配置类扩展

**目标:** 让 `Industry` 模型、`IndustryConfig` dataclass 和 Pydantic schema 都支持 `compliance_mode`、`webhook_url`、`auto_export_enabled`。

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


def test_industry_create_has_compliance_fields():
    data = IndustryCreate(
        name="测试",
        slug="test-ind",
        compliance_mode=True,
        webhook_url="https://example.com/hook",
        auto_export_enabled=True,
    )
    assert data.compliance_mode is True
    assert data.webhook_url == "https://example.com/hook"
    assert data.auto_export_enabled is True


def test_industry_model_has_compliance_columns():
    ind = Industry(name="测试", slug="test-ind")
    assert hasattr(ind, "compliance_mode")
    assert hasattr(ind, "webhook_url")
    assert hasattr(ind, "auto_export_enabled")


def test_industry_config_has_compliance_fields():
    cfg = IndustryConfig(
        name="测试", slug="test-ind", keywords=["a"], categories=["c"],
        compliance_mode=True,
        webhook_url="https://example.com/hook",
        auto_export_enabled=True,
    )
    assert cfg.compliance_mode is True
    assert cfg.webhook_url == "https://example.com/hook"
    assert cfg.auto_export_enabled is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
python -m pytest tests/server/test_models_schemas.py -v
```

Expected: 3 FAIL，字段不存在。

- [ ] **Step 3: 修改 Industry 模型**

在 `server/models/industry.py` 中 `Industry` 类里，在 `is_active` 字段之前插入：

```python
    compliance_mode = Column(Boolean, default=False)
    webhook_url = Column(String(512), default="")
    auto_export_enabled = Column(Boolean, default=False)
```

- [ ] **Step 4: 修改 IndustryConfig**

在 `core/config.py` 的 `IndustryConfig` dataclass 中，在 `collect_video_limit` 字段之后添加：

```python
    compliance_mode: bool = False
    webhook_url: str = ""
    auto_export_enabled: bool = False
```

- [ ] **Step 5: 修改 Pydantic schemas**

在 `server/schemas/industry.py` 中：

`IndustryCreate` 类在 `collect_video_limit` 之后添加：

```python
    compliance_mode: bool = False
    webhook_url: str = ""
    auto_export_enabled: bool = False
```

`IndustryUpdate` 类在 `is_active` 之前添加：

```python
    compliance_mode: bool | None = None
    webhook_url: str | None = None
    auto_export_enabled: bool | None = None
```

`IndustryOut` 类在 `is_active` 之前添加：

```python
    compliance_mode: bool = False
    webhook_url: str = ""
    auto_export_enabled: bool = False
```

- [ ] **Step 6: 运行测试确认通过**

```bash
python -m pytest tests/server/test_models_schemas.py -v
```

Expected: 3 PASS。

- [ ] **Step 7: 提交**

```bash
git add server/models/industry.py core/config.py server/schemas/industry.py tests/server/test_models_schemas.py
git commit -m "feat(phase1): add compliance fields to Industry model, config and schemas"
```

---

## Task 2: 创建线索导出服务

**目标:** 新增 `server/services/export.py`，支持按查询结果流式生成 CSV/Excel。

**Files:**
- Create: `server/services/export.py`
- Test: `tests/server/services/test_export.py`

- [ ] **Step 1: 确认依赖**

```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
python -c "import openpyxl" 2>/dev/null && echo "openpyxl OK" || echo "openpyxl missing"
```

如果缺失：

```bash
pip install openpyxl
```

- [ ] **Step 2: 写失败测试**

```python
# tests/server/services/test_export.py
import io
import csv
from server.services.export import generate_csv, generate_xlsx


def test_generate_csv_with_rows():
    rows = [
        {"id": 1, "platform": "douyin", "user_name": "u1", "text": "hello"},
        {"id": 2, "platform": "douyin", "user_name": "u2", "text": "world"},
    ]
    fields = ["id", "platform", "user_name", "text"]
    output = generate_csv(rows, fields=fields)
    content = "".join(output)
    reader = csv.DictReader(io.StringIO(content))
    data = list(reader)
    assert len(data) == 2
    assert data[0]["user_name"] == "u1"


def test_generate_xlsx_with_rows():
    rows = [
        {"id": 1, "platform": "douyin", "user_name": "u1", "text": "hello"},
    ]
    fields = ["id", "platform", "user_name", "text"]
    output = generate_xlsx(rows, fields=fields)
    data = output.read()
    assert data.startswith(b"PK")  # XLSX is a zip
    assert len(data) > 100
```

- [ ] **Step 3: 运行测试确认失败**

```bash
python -m pytest tests/server/services/test_export.py -v
```

Expected: 2 FAIL，模块不存在。

- [ ] **Step 4: 实现导出服务**

创建 `server/services/export.py`：

```python
"""Lead export generators (CSV/Excel)."""

import csv
import io
from typing import Iterable

from openpyxl import Workbook
from openpyxl.utils import get_column_letter


DEFAULT_EXPORT_FIELDS = [
    "id",
    "platform",
    "keyword",
    "source_creator",
    "source_video_desc",
    "user_name",
    "unique_id",
    "short_id",
    "douyin_id",
    "text",
    "matched_categories",
    "ai_reply",
    "status",
    "error",
    "fetched_at",
    "processed_at",
]

FIELD_TITLES = {
    "id": "线索ID",
    "platform": "平台",
    "keyword": "来源关键词",
    "source_creator": "博主",
    "source_video_desc": "视频描述",
    "user_name": "用户昵称",
    "unique_id": "用户唯一ID",
    "short_id": "Short ID",
    "douyin_id": "抖音号",
    "text": "评论内容",
    "matched_categories": "意图分类",
    "ai_reply": "AI回复文案",
    "status": "状态",
    "error": "失败原因",
    "fetched_at": "采集时间",
    "processed_at": "处理时间",
}


def normalize_export_row(row: dict, fields: list[str]) -> dict:
    """Convert a TaskQueue dict/row into flat string values for export."""
    result = {}
    for field in fields:
        value = row.get(field)
        if value is None:
            value = ""
        result[field] = str(value)
    return result


def generate_csv(rows: Iterable[dict], fields: list[str] | None = None) -> Iterable[str]:
    """Yield CSV lines as strings (StreamingResponse compatible)."""
    fields = fields or DEFAULT_EXPORT_FIELDS
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writerow({f: FIELD_TITLES.get(f, f) for f in fields})
    yield output.getvalue()
    output.close()

    for row in rows:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writerow(normalize_export_row(row, fields))
        yield output.getvalue()
        output.close()


def generate_xlsx(rows: Iterable[dict], fields: list[str] | None = None) -> io.BytesIO:
    """Generate an XLSX workbook in memory."""
    fields = fields or DEFAULT_EXPORT_FIELDS
    wb = Workbook()
    ws = wb.active
    ws.title = "线索池"

    headers = [FIELD_TITLES.get(f, f) for f in fields]
    ws.append(headers)

    for row in rows:
        normalized = normalize_export_row(row, fields)
        ws.append([normalized[f] for f in fields])

    # Auto-width columns (capped)
    for i, _ in enumerate(fields, 1):
        col_letter = get_column_letter(i)
        ws.column_dimensions[col_letter].width = min(60, max(12, len(FIELD_TITLES.get(fields[i - 1], fields[i - 1])) + 2))

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/server/services/test_export.py -v
```

Expected: 2 PASS。

- [ ] **Step 6: 提交**

```bash
git add server/services/export.py tests/server/services/test_export.py
git commit -m "feat(phase1): add CSV/Excel lead export service"
```

---

## Task 3: 创建 Webhook 推送服务

**目标:** 新增 `server/services/webhook.py`，支持异步 POST 线索列表到 Webhook URL，并记录结果。

**Files:**
- Create: `server/services/webhook.py`
- Test: `tests/server/services/test_webhook.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/services/test_webhook.py
from unittest.mock import patch, MagicMock
from server.services.webhook import push_leads_to_webhook, WebhookPayload


def test_webhook_payload_building():
    payload = WebhookPayload(
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1, "user_name": "u1"}],
    )
    data = payload.to_dict()
    assert data["industry_slug"] == "recruitment"
    assert len(data["leads"]) == 1


@patch("server.services.webhook.httpx.post")
def test_push_leads_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    mock_post.return_value = mock_resp

    result = push_leads_to_webhook(
        webhook_url="https://example.com/hook",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1, "user_name": "u1"}],
    )
    assert result["ok"] is True
    assert result["status_code"] == 200
    mock_post.assert_called_once()


@patch("server.services.webhook.httpx.post")
def test_push_leads_failure(mock_post):
    mock_post.side_effect = Exception("connection error")
    result = push_leads_to_webhook(
        webhook_url="https://example.com/hook",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1}],
    )
    assert result["ok"] is False
    assert "connection error" in result["error"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/services/test_webhook.py -v
```

Expected: 3 FAIL。

- [ ] **Step 3: 实现 Webhook 服务**

创建 `server/services/webhook.py`：

```python
"""Webhook push service for lead distribution."""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("thunder.webhook")


@dataclass
class WebhookPayload:
    industry_slug: str
    industry_name: str
    leads: list[dict[str, Any]]
    event: str = "leads.available"
    sent_at: str | None = None

    def __post_init__(self):
        if self.sent_at is None:
            self.sent_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def push_leads_to_webhook(
    webhook_url: str,
    industry_slug: str,
    industry_name: str,
    leads: list[dict[str, Any]],
    timeout: float = 10.0,
) -> dict:
    """POST leads to external webhook URL. Returns result dict for logging."""
    if not webhook_url:
        return {"ok": False, "error": "webhook_url empty"}

    payload = WebhookPayload(
        industry_slug=industry_slug,
        industry_name=industry_name,
        leads=leads,
    )

    try:
        resp = httpx.post(
            webhook_url,
            content=payload.to_json(),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        result = {
            "ok": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "response_preview": resp.text[:500],
        }
        if not result["ok"]:
            result["error"] = f"webhook returned {resp.status_code}"
        log.info("Webhook push to %s: %s", webhook_url, result)
        return result
    except Exception as e:
        log.warning("Webhook push failed: %s", e)
        return {"ok": False, "error": str(e)[:500]}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/server/services/test_webhook.py -v
```

Expected: 3 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/services/webhook.py tests/server/services/test_webhook.py
git commit -m "feat(phase1): add webhook push service for leads"
```

---

## Task 4: 实现导出 API

**目标:** 在 `server/api/leads.py` 新增 `POST /api/leads/export`，按条件导出 CSV 或 XLSX。

**Files:**
- Modify: `server/api/leads.py`
- Test: `tests/server/api/test_leads.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_leads.py
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_export_csv_requires_auth():
    resp = client.post("/api/leads/export", json={"industry_slug": "recruitment", "format": "csv"})
    assert resp.status_code in (401, 403)


def test_export_csv_returns_file(monkeypatch):
    # Mock auth and DB query
    from server import auth
    from server.models import task as task_module
    from server.models.task import TaskQueue

    class FakeUser:
        id = "user-1"

    def fake_get_current_user():
        return FakeUser()

    monkeypatch.setattr(auth, "get_current_user", fake_get_current_user)

    class FakeRow:
        id = 1
        platform = "douyin"
        keyword = "当兵"
        source_creator = "兵爸"
        source_video_desc = ""
        user_name = "u1"
        unique_id = "uid1"
        short_id = ""
        douyin_id = ""
        text = "我想当兵"
        matched_categories = "[]"
        ai_reply = ""
        status = "pending"
        error = ""
        fetched_at = "2026-06-15T10:00:00"
        processed_at = ""

    class FakeQuery:
        def filter(self, *a, **k): return self
        def count(self): return 1
        def order_by(self, *a): return self
        def limit(self, n): return self
        def offset(self, n): return [FakeRow()]

    monkeypatch.setattr(task_module, "TaskQueue", TaskQueue)
    # Patch SessionLocal used inside endpoint
    import server.api.leads as leads_module

    class FakeSession:
        def query(self, model): return FakeQuery()
        def close(self): pass

    monkeypatch.setattr(leads_module, "SessionLocal", FakeSession)

    resp = client.post("/api/leads/export", json={"industry_slug": "recruitment", "format": "csv"})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "我想当兵" in resp.text
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/api/test_leads.py -v
```

Expected: 2 FAIL（端点不存在或认证失败）。

- [ ] **Step 3: 实现导出 API**

在 `server/api/leads.py` 顶部新增导入：

```python
from fastapi.responses import StreamingResponse
from io import BytesIO
from datetime import datetime, timezone
from server.services.export import generate_csv, generate_xlsx, DEFAULT_EXPORT_FIELDS
```

在 `server/api/leads.py` 中新增 Pydantic 模型：

```python
class LeadExportRequest(BaseModel):
    industry_slug: str
    status: str | None = None
    format: str = "xlsx"  # csv or xlsx
    limit: int = Field(default=5000, ge=1, le=10000)
    fields: list[str] | None = None
```

在 `server/api/leads.py` 末尾新增路由：

```python
@router.post("/export")
def export_leads(
    req: LeadExportRequest,
    current_user = Depends(get_current_user),
):
    """Export leads as CSV or XLSX."""
    from server.models import SessionLocal
    from server.models.task import TaskQueue

    db = SessionLocal()
    try:
        query = db.query(TaskQueue).filter(
            TaskQueue.industry_slug == req.industry_slug,
            TaskQueue.owner_user_id == current_user.id,
        )
        if req.status:
            query = query.filter(TaskQueue.status == req.status)

        total = query.count()
        if total > req.limit:
            raise HTTPException(
                status_code=400,
                detail=f"结果 {total} 条超过限制 {req.limit}，请缩小筛选范围",
            )

        rows = query.order_by(TaskQueue.fetched_at.desc()).limit(req.limit).offset(0).all()
        fields = req.fields or DEFAULT_EXPORT_FIELDS

        # Normalize rows to dicts
        lead_rows = []
        for r in rows:
            d = {c.name: getattr(r, c.name) for c in TaskQueue.__table__.columns}
            # Flatten matched_categories JSON into string
            d["matched_categories"] = d.get("matched_categories", "")
            lead_rows.append(d)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"leads_{req.industry_slug}_{timestamp}"

        if req.format == "csv":
            return StreamingResponse(
                generate_csv(lead_rows, fields=fields),
                media_type="text/csv; charset=utf-8-sig",
                headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
            )
        elif req.format == "xlsx":
            buffer = generate_xlsx(lead_rows, fields=fields)
            return StreamingResponse(
                buffer,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}.xlsx"},
            )
        else:
            raise HTTPException(status_code=400, detail="format 必须是 csv 或 xlsx")
    finally:
        db.close()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/server/api/test_leads.py -v
```

Expected: 2 PASS（可能需要调整 mock）。

- [ ] **Step 5: 提交**

```bash
git add server/api/leads.py tests/server/api/test_leads.py
git commit -m "feat(phase1): add POST /api/leads/export endpoint"
```

---

## Task 5: 实现行业合规配置 API

**目标:** 在 `server/api/industries.py` 新增合规配置更新与 Webhook 测试接口，并在 `_to_industry_config` 中传递新增字段。

**Files:**
- Modify: `server/api/industries.py`
- Test: `tests/server/api/test_industries_compliance.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_industries_compliance.py
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_update_compliance_config_requires_auth():
    resp = client.put("/api/industries/ind-1/compliance-config", json={"compliance_mode": True})
    assert resp.status_code in (401, 403)


def test_webhook_test_requires_auth():
    resp = client.post("/api/industries/ind-1/webhook-test")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/server/api/test_industries_compliance.py -v
```

Expected: 2 FAIL。

- [ ] **Step 3: 修改 _to_industry_config 传递新字段**

在 `server/api/industries.py` 的 `_to_industry_config` 函数末尾，返回 `IndustryConfig` 前添加：

```python
        compliance_mode=bool(getattr(industry, "compliance_mode", False)),
        webhook_url=getattr(industry, "webhook_url", "") or "",
        auto_export_enabled=bool(getattr(industry, "auto_export_enabled", False)),
```

- [ ] **Step 4: 新增合规配置请求模型与路由**

在 `server/api/industries.py` 中新增模型：

```python
class ComplianceConfigUpdate(BaseModel):
    compliance_mode: bool | None = None
    webhook_url: str | None = None
    auto_export_enabled: bool | None = None
```

在 `server/api/industries.py` 末尾新增路由（放在 `_get_owned_industry` 定义之前或之后均可，但需在函数定义之后）：

```python
@router.put("/{industry_id}/compliance-config", response_model=IndustryOut)
def update_compliance_config(
    industry_id: str,
    body: ComplianceConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    if body.compliance_mode is not None:
        ind.compliance_mode = body.compliance_mode
    if body.webhook_url is not None:
        ind.webhook_url = body.webhook_url
    if body.auto_export_enabled is not None:
        ind.auto_export_enabled = body.auto_export_enabled
    db.commit()
    db.refresh(ind)
    return ind


@router.post("/{industry_id}/webhook-test")
def test_webhook(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    if not ind.webhook_url:
        raise HTTPException(status_code=400, detail="未配置 Webhook URL")

    from server.services.webhook import push_leads_to_webhook
    result = push_leads_to_webhook(
        webhook_url=ind.webhook_url,
        industry_slug=ind.slug,
        industry_name=ind.name,
        leads=[{
            "id": 0,
            "user_name": "测试用户",
            "text": "这是一条测试线索",
            "status": "pending",
        }],
    )
    return result
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/server/api/test_industries_compliance.py -v
```

Expected: 2 PASS（可能需要根据实际认证方式调整）。

- [ ] **Step 6: 提交**

```bash
git add server/api/industries.py tests/server/api/test_industries_compliance.py
git commit -m "feat(phase1): add compliance config and webhook test APIs"
```

---

## Task 6: 发送入口合规拦截

**目标:** 在 `core/task/worker.py` 的 `run_senders()` 中拦截合规模式项目；同时修复 Celery `run_send_batch` 使用 DB 配置而非 YAML，确保合规字段生效。

**Files:**
- Modify: `core/task/worker.py`
- Modify: `adapters/celery/send.py`
- Test: `tests/core/task/test_worker_compliance.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/task/test_worker_compliance.py
from unittest.mock import patch, MagicMock
from core.task.worker import run_senders
from core.config import IndustryConfig


def test_run_senders_skips_when_compliance_mode_enabled():
    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["a"],
        categories=["c"],
        compliance_mode=True,
    )
    result = run_senders(industry, device_ids=[])
    assert result["ok"] is True
    assert result.get("skipped") is True
    assert "compliance_mode" in result["reason"]


def test_run_senders_runs_normally_without_compliance_mode():
    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["a"],
        categories=["c"],
        compliance_mode=False,
    )
    with patch("core.task.worker.load_active_devices") as mock_load:
        mock_load.return_value = []
        result = run_senders(industry, device_ids=[])
        assert result["ok"] is False
        assert result.get("error") == "no available devices"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/core/task/test_worker_compliance.py -v
```

Expected: 2 FAIL（合规拦截不存在）。

- [ ] **Step 3: 实现合规拦截**

在 `core/task/worker.py` 的 `run_senders()` 函数开头，在 `log.info(...)` 之后、用户 ID 获取之前插入：

```python
    if getattr(industry, "compliance_mode", False):
        log.info("Compliance mode enabled for %s; skipping actual send.", getattr(industry, "slug", ""))
        return {
            "ok": True,
            "skipped": True,
            "reason": "compliance_mode",
            "industry_slug": getattr(industry, "slug", ""),
            "message": "合规模式已开启，仅采集不发送。",
        }
```

- [ ] **Step 4: 修复 Celery run_send_batch 使用 DB 配置**

修改 `adapters/celery/send.py` 中的 `run_send_batch`：

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

注意：调用 `run_send_batch.delay(...)` 的地方需要同步更新签名，传递 `user_id`。

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/core/task/test_worker_compliance.py -v
```

Expected: 2 PASS。

- [ ] **Step 6: 提交**

```bash
git add core/task/worker.py adapters/celery/send.py tests/core/task/test_worker_compliance.py
git commit -m "feat(phase1): compliance-mode intercept in send entry and Celery DB config"
```

---

## Task 7: 前端项目配置弹窗

**目标:** 在 `server/static/index.html` 的项目弹窗中增加合规模式开关、Webhook URL、自动推送开关和测试按钮。

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: 定位弹窗表单**

```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
grep -n "modal-industry" server/static/index.html | head -5
```

记录弹窗表单区域行号（约 520-700 行之间）。

- [ ] **Step 2: 在表单中添加合规配置折叠面板**

在弹窗表单 `</form>` 之前插入以下 HTML：

```html
                <!-- 合规与导出设置 -->
                <div class="mt-4 border border-slate-700/50 rounded-lg overflow-hidden">
                    <button type="button" onclick="toggleCompliancePanel()" class="w-full px-4 py-2 bg-slate-800/50 flex items-center justify-between text-xs font-semibold text-slate-300 hover:bg-slate-800">
                        <span>⚖️ 合规与导出设置</span>
                        <span id="compliance-panel-chevron">▼</span>
                    </button>
                    <div id="compliance-panel" class="hidden p-4 space-y-4 bg-slate-900/30">
                        <div class="flex items-center justify-between">
                            <div>
                                <p class="text-xs font-semibold text-slate-200">合规模式</p>
                                <p class="text-[10px] text-slate-500">开启后只采集评论并分类，不自动发送私信</p>
                            </div>
                            <label class="relative inline-flex items-center cursor-pointer">
                                <input type="checkbox" id="industry-compliance-mode" class="sr-only peer" onchange="onComplianceModeChange()">
                                <div class="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-cyan-600"></div>
                            </label>
                        </div>

                        <div id="compliance-webhook-section" class="space-y-2">
                            <label class="block text-xs font-semibold text-slate-300">Webhook 推送地址（可选）</label>
                            <input type="url" id="industry-webhook-url" placeholder="https://your-crm.com/webhook" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500">
                            <p class="text-[10px] text-slate-500">分类完成后自动将高意向线索 POST 到该地址</p>
                            <div class="flex items-center gap-2">
                                <label class="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                                    <input type="checkbox" id="industry-auto-export" class="rounded border-slate-700 bg-slate-900 text-cyan-600">
                                    <span>分类完成后自动推送</span>
                                </label>
                                <button type="button" onclick="testIndustryWebhook()" class="ml-auto px-2 py-1 rounded border border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/10 text-[10px] font-semibold">测试 Webhook</button>
                            </div>
                        </div>
                    </div>
                </div>
```

- [ ] **Step 3: 添加折叠/展开 JS 函数**

在 `<script>` 区域添加：

```javascript
        function toggleCompliancePanel() {
            const panel = document.getElementById('compliance-panel');
            const chevron = document.getElementById('compliance-panel-chevron');
            panel.classList.toggle('hidden');
            chevron.innerText = panel.classList.contains('hidden') ? '▼' : '▲';
        }

        function onComplianceModeChange() {
            const enabled = document.getElementById('industry-compliance-mode').checked;
            const webhookSection = document.getElementById('compliance-webhook-section');
            webhookSection.classList.toggle('opacity-50', !enabled);
            webhookSection.classList.toggle('pointer-events-none', !enabled);
        }

        async function testIndustryWebhook() {
            const urlInput = document.getElementById('industry-webhook-url');
            const url = urlInput.value.trim();
            if (!url) {
                showToast('请先填写 Webhook URL', 'warning');
                return;
            }
            const industryId = document.getElementById('industry-id')?.value;
            if (!industryId) {
                showToast('请先保存项目', 'warning');
                return;
            }
            try {
                const res = await apiFetch(`/api/industries/${industryId}/webhook-test`, { method: 'POST' });
                if (res.ok) {
                    showToast('Webhook 测试成功', 'success');
                } else {
                    showToast(`Webhook 测试失败: ${res.error || res.response_preview || '未知错误'}`, 'error');
                }
            } catch (e) {
                showToast(e.message || '测试失败', 'error');
            }
        }
```

- [ ] **Step 4: 修改表单提交逻辑读取新字段**

找到 `saveIndustry()` 或表单提交函数（通常在 1600-1750 行附近），在构造 payload 时新增：

```javascript
                compliance_mode: document.getElementById('industry-compliance-mode').checked,
                webhook_url: document.getElementById('industry-webhook-url').value.trim(),
                auto_export_enabled: document.getElementById('industry-auto-export').checked,
```

- [ ] **Step 5: 修改编辑回填逻辑**

在 `editIndustry(id)` 中，当从 `/api/industries/{id}` 加载数据后回填：

```javascript
                document.getElementById('industry-compliance-mode').checked = Boolean(ind.compliance_mode);
                document.getElementById('industry-webhook-url').value = ind.webhook_url || '';
                document.getElementById('industry-auto-export').checked = Boolean(ind.auto_export_enabled);
                onComplianceModeChange();
```

- [ ] **Step 6: 手动验证**

启动后端：

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

打开浏览器访问 `http://localhost:8000/static/index.html`，登录后进入项目配置：
- 点击"新建项目"
- 确认出现"合规与导出设置"折叠面板
- 切换合规模式开关，Webhook 区域是否变灰
- 保存后重新编辑，确认字段回填正确

- [ ] **Step 7: 提交**

```bash
git add server/static/index.html
git commit -m "feat(phase1): add compliance config UI in industry modal"
```

---

## Task 8: 前端控制中心适配

**目标:** 当项目开启合规模式时，控制中心隐藏"发送"按钮，显示"导出高意向线索"按钮和合规提示。

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: 定位控制中心渲染逻辑**

```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
grep -n "overview-btn-send\|overview-btn-collect\|can_send" server/static/index.html | head -20
```

- [ ] **Step 2: 修改按钮显示逻辑**

在渲染项目卡片或就绪度时，如果 `ind.compliance_mode` 为 true：

```javascript
                const isCompliance = ind.compliance_mode;
                const btnSend = document.getElementById('overview-btn-send');
                const btnCollect = document.getElementById('overview-btn-collect');
                if (btnSend) {
                    btnSend.innerText = isCompliance ? '导出高意向线索' : '发送';
                    btnSend.onclick = isCompliance
                        ? () => { router.navigate('tasks'); setTimeout(() => openExportModal(ind.slug), 200); }
                        : () => triggerOverviewSend();
                    btnSend.disabled = !st.can_send && !isCompliance;
                }
```

- [ ] **Step 3: 在就绪度列表增加合规提示**

在渲染就绪度项目时，如果合规模式开启，增加一条提示项：

```javascript
                if (isCompliance) {
                    renderReadinessItem('合规模式', '已开启：只采集不发送，线索可导出或推送至 CRM', true, '查看配置', `editIndustry('${ind.id}')`);
                }
```

- [ ] **Step 4: 手动验证**

在浏览器中：
- 选择一个合规模式项目，确认控制中心"发送"按钮变成"导出高意向线索"
- 点击按钮跳转线索池

- [ ] **Step 5: 提交**

```bash
git add server/static/index.html
git commit -m "feat(phase1): adapt overview buttons for compliance mode"
```

---

## Task 9: 前端线索池导出

**目标:** 在线索池页面添加导出按钮和导出配置弹窗。

**Files:**
- Modify: `server/static/index.html`

- [ ] **Step 1: 定位线索池头部**

行号约 395-420 行，包含 `task-filter-industry`、`task-filter-status`、`task-retry-all-btn`。

- [ ] **Step 2: 在头部添加导出按钮**

在 `task-retry-all-btn` 之后添加：

```html
                    <button onclick="openExportModal()" class="px-3 py-1.5 rounded-lg border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 text-xs font-semibold">
                        导出 Excel
                    </button>
                    <button onclick="openExportModal('csv')" class="px-3 py-1.5 rounded-lg border border-slate-500/30 text-slate-300 hover:bg-slate-500/10 text-xs font-semibold">
                        导出 CSV
                    </button>
```

- [ ] **Step 3: 添加导出弹窗 HTML**

在 `</body>` 之前或其他弹窗区域添加：

```html
    <!-- Export Modal -->
    <div id="modal-export" class="fixed inset-0 z-50 hidden items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
        <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md shadow-2xl">
            <div class="p-5 border-b border-slate-800 flex justify-between items-center">
                <h3 class="font-bold text-lg font-display text-slate-100">导出线索</h3>
                <button onclick="closeExportModal()" class="text-slate-500 hover:text-slate-300">✕</button>
            </div>
            <div class="p-5 space-y-4">
                <p class="text-xs text-slate-400">将导出当前筛选条件下的线索，最多 5000 条。</p>
                <input type="hidden" id="export-format" value="xlsx">
                <div>
                    <label class="block text-xs font-semibold text-slate-300 mb-1">格式</label>
                    <select id="export-format-select" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200">
                        <option value="xlsx">Excel (.xlsx)</option>
                        <option value="csv">CSV (.csv)</option>
                    </select>
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-300 mb-1">状态</label>
                    <select id="export-status-select" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200">
                        <option value="">全部</option>
                        <option value="pending">待处理</option>
                        <option value="done">已发送</option>
                        <option value="failed">失败</option>
                    </select>
                </div>
                <div id="export-loading" class="hidden text-center py-2">
                    <span class="text-xs text-cyan-400">正在生成文件...</span>
                </div>
            </div>
            <div class="p-5 border-t border-slate-800 flex justify-end gap-3">
                <button onclick="closeExportModal()" class="px-4 py-2 rounded-lg border border-slate-700 text-slate-300 text-xs hover:bg-slate-800">取消</button>
                <button onclick="confirmExportLeads()" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold">确认导出</button>
            </div>
        </div>
    </div>
```

- [ ] **Step 4: 添加导出弹窗 JS 逻辑**

```javascript
        function openExportModal(defaultFormat) {
            const modal = document.getElementById('modal-export');
            const formatSelect = document.getElementById('export-format-select');
            if (defaultFormat) {
                formatSelect.value = defaultFormat;
            }
            modal.classList.replace('hidden', 'flex');
        }

        function closeExportModal() {
            document.getElementById('modal-export').classList.replace('flex', 'hidden');
            document.getElementById('export-loading').classList.add('hidden');
        }

        async function confirmExportLeads() {
            const industryId = document.getElementById('task-filter-industry').value;
            if (!industryId) {
                showToast('请先选择项目', 'warning');
                return;
            }
            const format = document.getElementById('export-format-select').value;
            const status = document.getElementById('export-status-select').value;
            document.getElementById('export-loading').classList.remove('hidden');

            try {
                const token = localStorage.getItem('thunder_token') || '';
                const resp = await fetch('/api/leads/export', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': token ? `Bearer ${token}` : '',
                    },
                    body: JSON.stringify({
                        industry_slug: industryId,
                        format: format,
                        status: status || undefined,
                    }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || '导出失败');
                }
                const blob = await resp.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                const disposition = resp.headers.get('content-disposition') || '';
                const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
                a.download = filenameMatch ? filenameMatch[1] : `leads.${format}`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                showToast('导出成功', 'success');
                closeExportModal();
            } catch (e) {
                showToast(e.message || '导出失败', 'error');
            } finally {
                document.getElementById('export-loading').classList.add('hidden');
            }
        }
```

- [ ] **Step 5: 手动验证**

在浏览器中：
- 进入线索池页面
- 选择一个项目
- 点击"导出 Excel"按钮
- 确认文件下载且字段正确

- [ ] **Step 6: 提交**

```bash
git add server/static/index.html
git commit -m "feat(phase1): add lead export UI in tasks view"
```

---

## Task 10: 集成测试与回归

**目标:** 验证完整流程，确保原有发送能力未被破坏。

**Files:**
- Run tests across `tests/`
- Manual verification

- [ ] **Step 1: 运行全部新增测试**

```bash
cd C:/Users/Administrator/Desktop/shemeihuoke
python -m pytest tests/ -v
```

Expected: 所有新增测试 PASS。

- [ ] **Step 2: 检查原有发送链路未被破坏**

创建一个非合规模式项目，确保：
- 点击"发送"按钮仍然触发 `run_senders`
- 设备调度逻辑正常（即使没有真机，也返回"no available devices"或正常进入调度）

- [ ] **Step 3: 验证合规模式项目不发送**

创建一个合规模式项目，点击原"发送"位置按钮：
- 不应看到设备调度日志
- 返回信息应包含"合规模式"

- [ ] **Step 4: 验证导出文件内容**

使用真实或测试数据，导出一个 Excel：
- 确认字段顺序与 `DEFAULT_EXPORT_FIELDS` 一致
- 确认中文字符正常显示
- 确认状态筛选生效

- [ ] **Step 5: 验证 Webhook 测试**

使用一个测试 Webhook 服务（如 https://webhook.site），配置到项目中，点击"测试 Webhook"：
- 确认收到 POST 请求
- 确认 payload 包含 `leads` 数组

- [ ] **Step 6: 最终提交**

```bash
git add .
git commit -m "feat(phase1): complete data export and compliance mode"
```

---

## 自检清单

### Spec 覆盖度

| Spec 要求 | 对应任务 |
|---|---|
| `sa_industries` 新增合规字段 | Task 1 |
| `IndustryConfig` 新增字段 | Task 1 |
| CSV/Excel 导出 API | Task 2 + Task 4 |
| Webhook 配置与测试接口 | Task 3 + Task 5 |
| `run_senders` 合规拦截 | Task 6 |
| Celery 使用 DB 配置 | Task 6 |
| 前端项目弹窗合规配置 | Task 7 |
| 控制中心适配 | Task 8 |
| 线索池导出按钮 | Task 9 |
| 测试与回归 | Task 10 |

### Placeholder 检查

- [ ] 无 "TBD"/"TODO"
- [ ] 无 "add appropriate error handling" 等模糊描述
- [ ] 每个代码步骤都包含实际代码
- [ ] 函数名/字段名前后一致：`compliance_mode`、`webhook_url`、`auto_export_enabled`

### 类型一致性

- `compliance_mode` 全为 `bool`
- `webhook_url` 全为 `str`（数据库 `String(512)`）
- `auto_export_enabled` 全为 `bool`
- API 路径统一使用 `/api/industries/{industry_id}/compliance-config` 和 `/api/industries/{industry_id}/webhook-test`
