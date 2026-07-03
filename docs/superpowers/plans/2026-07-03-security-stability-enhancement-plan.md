# Security/Stability Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将剩余技术债统一归集到下一版本「安全/稳定性增强」专项迭代，完成异常语义、数据库配额一致性、证据权限绑定和运营体验稳定性的工程化改造。

**Architecture:** 本专项不做零散小补丁，采用“契约先行、测试封锁、分阶段上线”的方式推进。先定义错误语义与证据元数据契约，再改造调度器并发一致性，最后补齐运营体验的状态、统计和可恢复能力。

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, SQLite/PostgreSQL, Pydantic, Pytest, existing SaaS Web UI static frontend.

---

## 1. 当前剩余核心技术债梳理

| 编号 | 技术债 | 当前状态 | 风险 | 建议归属 |
| --- | --- | --- | --- | --- |
| TD-01 | 全局异常处理语义不统一 | `server/api/*`, `server/workers.py`, `core/task/*` 存在大量 `except Exception`，部分只返回空数据或字符串错误 | 前端无法区分用户错误、设备错误、权限错误、系统错误；日志排障困难 | 安全/稳定性增强 |
| TD-02 | 未知数据库方言下配额行创建存在竞争 | `core/task/scheduler.py::_ensure_quota_row` 对 SQLite/PostgreSQL 有冲突插入，对未知 dialect 采用 query-then-insert | 并发 claim 时可能重复插入或触发 IntegrityError，影响每日发送上限 | 安全/稳定性增强 |
| TD-03 | 证据文件只校验目录，没有绑定用户身份 | `server/api/devices.py::get_acceptance_evidence_file` 限制在 `data/acceptance`，但没有使用 report metadata 校验 user/device/job 所属关系 | 多租户下用户可能读取同目录下其他用户测试证据 | 安全/稳定性增强 |
| TD-04 | 运营体验优化项分散 | 库存补采、失败重试、统计窗口、任务状态、取消反馈、异常可见性分散在 API/worker/UI | 用户看到“完成/失败/取消”时原因不透明，人工测试成本高 | 安全/稳定性增强 |

## 2. 复杂度与影响范围评估

| 技术债 | 复杂度 | 影响范围 | 为什么不适合小范围仓促修改 |
| --- | --- | --- | --- |
| TD-01 异常语义 | 高 | API 返回结构、前端 toast、worker 日志、任务状态、测试用例 | 直接替换异常处理会改变现有接口返回，可能让前端误判任务状态 |
| TD-02 配额竞争 | 中高 | `IndustryDailyQuota`, `TaskQueue` claim/release/commit, SQLite/PostgreSQL/未来数据库 | 需要并发测试验证，一行 try/except 可能掩盖 quota 泄露或重复 reserve |
| TD-03 证据绑定 | 中高 | 验收脚本、报告 JSON、文件下载 API、设备归属、用户认证 | 需要设计兼容旧证据文件的迁移策略，否则当前验收报告链接会失效 |
| TD-04 运营体验 | 中 | Web UI 展示、任务 API、统计 API、发送/取消流程 | 体验项依赖后端状态语义，前端先改会造成“显示好看但事实不准” |

**结论：** 以上四类问题均跨越后端模型、API 契约、worker 行为和前端展示，不应作为临时小补丁直接上线。下一版本必须以专项迭代推进，先冻结接口契约，再按测试驱动分批落地。

## 3. 文件结构与职责

### 新增文件

- `server/errors.py`  
  定义统一错误码、错误类别、HTTP 映射和 `AppError` 基类。

- `tests/server/test_errors.py`  
  验证错误码序列化、HTTP 状态映射和敏感信息截断。

- `tests/core/task/test_quota_concurrency.py`  
  验证 quota row 创建、reserve、release、commit 在并发场景下不超限。

- `tests/server/api/test_acceptance_evidence_ownership.py`  
  验证证据文件必须匹配当前用户、设备和 report metadata。

- `tests/server/api/test_operational_status_contract.py`  
  验证发送、取消、失败、重试、库存补采相关 API 返回统一状态字段。

### 修改文件

- `server/main.py`  
  注册全局异常处理器，统一返回 `{ok, error, code, message, correlation_id}`。

- `server/api/devices.py`  
  将证据下载从目录校验升级为目录校验 + report metadata 所属权校验。

- `core/task/scheduler.py`  
  将 quota row 创建封装为可捕获 `IntegrityError` 的事务安全逻辑，并将失败原因语义化。

- `server/workers.py`  
  把 cancel/send/collect 的异常结果改为统一错误码和可恢复状态。

- `server/api/jobs.py`  
  返回任务运行状态、取消状态、失败是否可重试、quota 是否释放。

- `server/api/leads.py`  
  失败线索一键重试 API 返回标准结果，避免前端只显示模糊成功/失败。

- `server/static/index.html`, `server/static/js/*.js`  
  只在后端契约稳定后更新运营状态显示、重试按钮、取消反馈、证据访问错误提示。

## 4. 下一版本排期计划

| 阶段 | 周期 | 目标 | 上线策略 |
| --- | --- | --- | --- |
| Phase 1 | 1 天 | 锁定错误语义、状态枚举、证据元数据格式、quota 并发规则 | 只提交测试和文档，不改生产行为 |
| Phase 2 | 2 天 | 实现统一错误模型与 API exception handler | 后端灰度，保持旧字段兼容 |
| Phase 3 | 2 天 | 改造 quota 并发一致性并补并发测试 | 先 SQLite/PostgreSQL 回归，再扩展未知 dialect fallback |
| Phase 4 | 2 天 | 实现证据文件 user/device/job 绑定 | 新证据强校验，旧证据只允许管理员或生成者访问 |
| Phase 5 | 2 天 | 运营体验闭环：取消、失败重试、库存补采、统计窗口、前端提示 | Web UI 联调后上线 |
| Phase 6 | 1 天 | 全链路验收、回滚方案、发布说明 | 小流量真实设备测试后发布 |

## 5. 详细实施任务

### Task 1: 定义统一异常语义契约

**Files:**
- Create: `server/errors.py`
- Create: `tests/server/test_errors.py`
- Modify: `server/main.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/test_errors.py
from server.errors import AppError, ErrorCode, serialize_error


def test_app_error_serializes_without_sensitive_traceback():
    err = AppError(
        code=ErrorCode.DEVICE_OFFLINE,
        message="Device offline",
        detail="adb serial abc failed",
        http_status=409,
    )

    payload = serialize_error(err, correlation_id="cid-1")

    assert payload == {
        "ok": False,
        "code": "DEVICE_OFFLINE",
        "message": "Device offline",
        "detail": "adb serial abc failed",
        "correlation_id": "cid-1",
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\server\test_errors.py -q`  
Expected: FAIL，提示 `No module named 'server.errors'`。

- [ ] **Step 3: 实现错误模型**

```python
# server/errors.py
from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEVICE_KEYBOARD_NOT_READY = "DEVICE_KEYBOARD_NOT_READY"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_NOT_CANCELLABLE = "JOB_NOT_CANCELLABLE"
    EVIDENCE_FORBIDDEN = "EVIDENCE_FORBIDDEN"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    UPSTREAM_FAILED = "UPSTREAM_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str,
        detail: str = "",
        http_status: int = 400,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail[:500]
        self.http_status = http_status
        self.context = context or {}


def serialize_error(error: AppError, *, correlation_id: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "code": error.code.value,
        "message": error.message,
        "detail": error.detail,
        "correlation_id": correlation_id,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests\server\test_errors.py -q`  
Expected: PASS。

- [ ] **Step 5: 在 FastAPI 注册全局异常处理器**

在 `server/main.py` 中增加：

```python
from fastapi import Request
from fastapi.responses import JSONResponse
import logging

from server.errors import AppError, ErrorCode, serialize_error

log = logging.getLogger("thunder.api.errors")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    correlation_id = getattr(request.state, "correlation_id", "")
    return JSONResponse(
        status_code=exc.http_status,
        content=serialize_error(exc, correlation_id=correlation_id),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    correlation_id = getattr(request.state, "correlation_id", "")
    log.exception("Unhandled request error correlation_id=%s", correlation_id)
    error = AppError(
        code=ErrorCode.INTERNAL_ERROR,
        message="Internal server error",
        detail="Unexpected server error",
        http_status=500,
    )
    return JSONResponse(
        status_code=500,
        content=serialize_error(error, correlation_id=correlation_id),
    )
```

- [ ] **Step 6: 提交**

```powershell
git add server/errors.py tests/server/test_errors.py server/main.py
git commit -m "feat: add unified error contract"
```

### Task 2: 统一关键 API 的异常返回语义

**Files:**
- Modify: `server/api/devices.py`
- Modify: `server/api/jobs.py`
- Modify: `server/api/leads.py`
- Test: `tests/server/api/test_operational_status_contract.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_operational_status_contract.py
def test_device_not_found_uses_standard_error(client, auth_headers):
    res = client.post(
        "/api/devices/not-exist/prepare-keyboard",
        headers=auth_headers,
    )

    assert res.status_code == 404
    assert res.json()["ok"] is False
    assert res.json()["code"] == "DEVICE_NOT_FOUND"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\server\api\test_operational_status_contract.py -q`  
Expected: FAIL，当前接口返回 FastAPI 默认 `{"detail": ...}`。

- [ ] **Step 3: 扩展错误码并替换关键 HTTPException**

在 `server/errors.py` 的 `ErrorCode` 增加：

```python
DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
JOB_NOT_FOUND = "JOB_NOT_FOUND"
LEAD_NOT_FOUND = "LEAD_NOT_FOUND"
```

在 `server/api/devices.py` 中将设备不存在替换为：

```python
from server.errors import AppError, ErrorCode


def _raise_device_not_found() -> None:
    raise AppError(
        code=ErrorCode.DEVICE_NOT_FOUND,
        message="Device not found",
        detail="The requested device does not exist or does not belong to current user",
        http_status=404,
    )
```

- [ ] **Step 4: 运行关键 API 测试**

Run: `.venv\Scripts\python.exe -m pytest tests\server\api\test_operational_status_contract.py tests\server\api\test_devices_evidence.py tests\server\api\test_auth.py -q`  
Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add server/errors.py server/api/devices.py server/api/jobs.py server/api/leads.py tests/server/api/test_operational_status_contract.py
git commit -m "feat: standardize operational api errors"
```

### Task 3: 修复未知数据库方言下配额竞争

**Files:**
- Modify: `core/task/scheduler.py`
- Test: `tests/core/task/test_quota_concurrency.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/core/task/test_quota_concurrency.py
from sqlalchemy.exc import IntegrityError

from core.task.scheduler import MatrixTaskScheduler
from server.models.task import IndustryDailyQuota


def test_unknown_dialect_quota_row_handles_integrity_race(db_session, monkeypatch):
    scheduler = MatrixTaskScheduler(industry_slug="ind", global_daily_limit=1)
    scheduler._db = db_session
    day = "2026-07-03"

    calls = {"n": 0}
    original_add = db_session.add

    def racing_add(obj):
        if isinstance(obj, IndustryDailyQuota) and calls["n"] == 0:
            calls["n"] += 1
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return original_add(obj)

    monkeypatch.setattr(db_session, "add", racing_add)
    monkeypatch.setattr(db_session.get_bind().dialect, "name", "unknown")

    scheduler._ensure_quota_row(db_session, day)

    assert db_session.query(IndustryDailyQuota).filter_by(industry_slug="ind", day=day).count() <= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\core\task\test_quota_concurrency.py -q`  
Expected: FAIL，未知 dialect fallback 未处理 `IntegrityError`。

- [ ] **Step 3: 实现 fallback 并发安全逻辑**

在 `core/task/scheduler.py` 中修改 `_ensure_quota_row`：

```python
from sqlalchemy.exc import IntegrityError


def _ensure_quota_row(self, db, day: str) -> None:
    values = {
        "industry_slug": self.industry_slug,
        "day": day,
        "sent": 0,
        "reserved": 0,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        db.execute(
            sqlite_insert(IndustryDailyQuota)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["industry_slug", "day"])
        )
        return
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        db.execute(
            postgresql_insert(IndustryDailyQuota)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["industry_slug", "day"])
        )
        return

    quota = db.query(IndustryDailyQuota).filter(
        IndustryDailyQuota.industry_slug == self.industry_slug,
        IndustryDailyQuota.day == day,
    ).first()
    if quota is not None:
        return
    try:
        db.add(IndustryDailyQuota(**values))
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(IndustryDailyQuota).filter(
            IndustryDailyQuota.industry_slug == self.industry_slug,
            IndustryDailyQuota.day == day,
        ).first()
        if existing is None:
            raise
```

- [ ] **Step 4: 跑并发与调度回归**

Run: `.venv\Scripts\python.exe -m pytest tests\core\task\test_quota_concurrency.py tests\core\task\test_scheduler.py tests\server\test_workers.py -q`  
Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add core/task/scheduler.py tests/core/task/test_quota_concurrency.py
git commit -m "fix: make quota creation safe for fallback dialects"
```

### Task 4: 证据文件与用户身份绑定

**Files:**
- Modify: `scripts/smoke/real_device_acceptance.py`
- Modify: `server/api/devices.py`
- Test: `tests/server/api/test_acceptance_evidence_ownership.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/server/api/test_acceptance_evidence_ownership.py
import json


def test_evidence_file_requires_owner_metadata(client, auth_headers, tmp_path, monkeypatch):
    from server.api import devices

    base = tmp_path / "acceptance"
    base.mkdir()
    evidence = base / "shot.png"
    evidence.write_bytes(b"fakepng")
    report = base / "report.json"
    report.write_text(
        json.dumps(
            {
                "user_id": "other-user",
                "device_id": "device-1",
                "evidence_files": [str(evidence)],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(devices, "_ACCEPTANCE_OUTPUT_DIR", base)

    res = client.get(
        f"/api/devices/evidence/file?path={evidence}&report_path={report}",
        headers=auth_headers,
    )

    assert res.status_code == 403
    assert res.json()["code"] == "EVIDENCE_FORBIDDEN"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\server\api\test_acceptance_evidence_ownership.py -q`  
Expected: FAIL，当前接口没有 `report_path` 和 owner metadata 校验。

- [ ] **Step 3: 验收报告写入 owner metadata**

在 `scripts/smoke/real_device_acceptance.py` 生成 report 时加入：

```python
report["user_id"] = getattr(args, "user_id", "")
report["device_id"] = getattr(args, "device_id", "")
report["evidence_files"] = [
    path for path in [
        report.get("screenshot_path"),
        (report.get("observation") or {}).get("screenshot_path"),
    ]
    if path
]
```

在 `server/api/devices.py::_run_acceptance` 的 `Namespace` 里加入：

```python
user_id=device.user_id,
device_id=device.id,
```

- [ ] **Step 4: 下载接口校验 report ownership**

将 `get_acceptance_evidence_file` 改为：

```python
@router.get("/evidence/file")
def get_acceptance_evidence_file(
    path: str,
    report_path: str = "",
    current_user: User = Depends(get_current_user),
):
    evidence_path = _resolve_acceptance_evidence_path(path)
    if report_path:
        report_file = _resolve_acceptance_evidence_path(report_path)
        report = json.loads(report_file.read_text(encoding="utf-8"))
        if str(report.get("user_id") or "") != current_user.id:
            raise AppError(
                code=ErrorCode.EVIDENCE_FORBIDDEN,
                message="Evidence access denied",
                detail="Evidence report does not belong to current user",
                http_status=403,
            )
        allowed_files = {str(Path(item).resolve()) for item in report.get("evidence_files", [])}
        if str(evidence_path.resolve()) not in allowed_files:
            raise AppError(
                code=ErrorCode.EVIDENCE_FORBIDDEN,
                message="Evidence access denied",
                detail="Evidence file is not referenced by the report",
                http_status=403,
            )
    return FileResponse(str(evidence_path))
```

- [ ] **Step 5: 兼容旧证据**

没有 `report_path` 的旧链接保留目录校验，但前端新链接必须带 `report_path`。发布后 1 个版本内保留兼容，第 2 个版本切换为强制 report metadata。

- [ ] **Step 6: 跑证据与设备测试**

Run: `.venv\Scripts\python.exe -m pytest tests\server\api\test_acceptance_evidence_ownership.py tests\server\api\test_devices_evidence.py tests\server\api\test_frontend_contract.py -q`  
Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add scripts/smoke/real_device_acceptance.py server/api/devices.py tests/server/api/test_acceptance_evidence_ownership.py
git commit -m "feat: bind acceptance evidence to owning user"
```

### Task 5: 运营体验状态闭环

**Files:**
- Modify: `server/api/jobs.py`
- Modify: `server/api/leads.py`
- Modify: `server/api/stats.py`
- Modify: `server/static/js/jobs.js`
- Modify: `server/static/js/dashboard.js`
- Test: `tests/server/api/test_operational_status_contract.py`

- [ ] **Step 1: 定义后端状态契约测试**

```python
def test_job_status_exposes_cancel_and_retry_contract(client, auth_headers):
    res = client.get("/api/jobs?limit=1", headers=auth_headers)

    assert res.status_code == 200
    payload = res.json()
    assert "items" in payload or isinstance(payload, list)
    rows = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    if rows:
        row = rows[0]
        assert "status" in row
        assert "can_cancel" in row
        assert "can_retry" in row
        assert "failure_reason" in row
        assert "quota_released" in row
```

- [ ] **Step 2: 后端增加统一字段**

在 job 序列化函数中补齐：

```python
def _job_operational_flags(job) -> dict:
    status = str(getattr(job, "status", "") or "")
    return {
        "can_cancel": status in {"queued", "running", "cancelling"},
        "can_retry": status in {"failed", "cancelled"},
        "failure_reason": str(getattr(job, "error", "") or "")[:500],
        "quota_released": status in {"failed", "cancelled", "completed"},
    }
```

- [ ] **Step 3: 失败线索一键重试返回标准结果**

`server/api/leads.py` 的重试接口返回：

```python
return {
    "ok": True,
    "code": "LEADS_REQUEUED",
    "requeued": updated,
    "skipped": skipped,
    "message": f"已重新加入发送队列 {updated} 条",
}
```

- [ ] **Step 4: 前端状态展示**

`server/static/js/jobs.js` 使用后端字段渲染按钮：

```javascript
function renderJobActions(job) {
  const actions = [];
  if (job.can_cancel) actions.push(`<button data-action="cancel-job" data-id="${job.id}">取消</button>`);
  if (job.can_retry) actions.push(`<button data-action="retry-job" data-id="${job.id}">重试</button>`);
  return actions.join("");
}
```

- [ ] **Step 5: 跑运营契约测试**

Run: `.venv\Scripts\python.exe -m pytest tests\server\api\test_operational_status_contract.py tests\server\api\test_leads.py tests\server\api\test_stats.py tests\server\api\test_frontend_contract.py -q`  
Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add server/api/jobs.py server/api/leads.py server/api/stats.py server/static/js/jobs.js server/static/js/dashboard.js tests/server/api/test_operational_status_contract.py
git commit -m "feat: expose operational recovery state"
```

## 6. 上线验证标准

### 自动化验证门槛

必须全部通过：

```powershell
.venv\Scripts\python.exe -m pytest tests\server\test_errors.py tests\server\api\test_operational_status_contract.py tests\core\task\test_quota_concurrency.py tests\server\api\test_acceptance_evidence_ownership.py tests\core\task\test_scheduler.py tests\server\test_workers.py tests\server\api\test_devices_evidence.py tests\server\api\test_frontend_contract.py -q
```

```powershell
.venv\Scripts\python.exe -m compileall core server scripts tests
```

### 真实设备验证门槛

- 单设备 dry-run 验收报告可生成，证据链接必须可由本人访问。
- 其他用户访问该证据链接返回 `403 EVIDENCE_FORBIDDEN`。
- 单设备 live-send 成功后，任务状态从 `claimed` 到 `done`，quota `reserved -1` 且 `sent +1`。
- 点击取消发送后，任务状态进入 `cancelled` 或回到 `pending`，quota reservation 必须释放。
- 失败线索一键重试后，失败项回到 `pending`，前端显示 requeued 数量。
- 人工断开设备后，接口返回 `DEVICE_OFFLINE`，前端显示可理解错误，不显示 `[object Object]`。

### 回滚标准

出现以下任一情况必须回滚：

- 发送成功但 quota 未释放或重复计数。
- 用户可以访问其他用户证据文件。
- 前端无法登录或核心列表无法加载。
- 任务取消接口返回成功但 worker 仍继续发送。
- 真实设备发送链路连续 2 次出现无法解释的状态不一致。

## 7. 自检结论

- Spec coverage: 已覆盖异常语义、未知方言 quota 竞争、证据文件身份绑定、运营体验优化、复杂度评估、专项排期和上线验证标准。
- Placeholder scan: 文档每个任务都有文件、测试、实现方向、命令和预期结果。
- Type consistency: `AppError`, `ErrorCode`, `serialize_error`, `can_cancel`, `can_retry`, `quota_released`, `EVIDENCE_FORBIDDEN` 在任务间命名一致。
