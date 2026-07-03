# AI Matrix Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有雷霆捕获系统从功能完整状态升级为可验证、可观测、可取消、支持 30 台真实设备稳定执行的 AI Agent 矩阵系统。

**Architecture:** 保留现有 `FastAPI + SQLAlchemy + core/adapters` 分层，先建立 API 契约和任务状态机，再收紧 Agent 感知、发送结果确认及设备调度。Web UI 继续同源部署，但把 API、任务和设备逻辑从单文件 HTML 拆成小型模块，并用浏览器 E2E 和虚拟 30 设备压力测试作为发布门禁。

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x, Pydantic 2.x, pytest, Celery/Redis adapters, ADB, OCR/UI XML, Vanilla JavaScript, Playwright, SQLite/PostgreSQL

---

## File Structure

| Path | Responsibility |
|---|---|
| `tests/server/api/test_frontend_contract.py` | 前端调用和 FastAPI 路由、方法、关键响应字段契约 |
| `core/task/job_state.py` | collect/send 任务统一状态机和合法迁移 |
| `tests/server/test_job_lifecycle.py` | 启动、取消、超时、恢复、完成的任务生命周期 |
| `core/task/send_verifier.py` | 根据截图、OCR、UI 树判断私信是否真正发送成功 |
| `tests/core/task/test_send_verifier.py` | 发送结果判定的纯逻辑测试 |
| `tests/core/task/test_matrix_30_devices.py` | 30 台虚拟设备抢占、额度、熔断和取消压力测试 |
| `server/static/js/api.js` | Token、错误、超时、JSON/Blob 的统一 API 客户端 |
| `server/static/js/jobs.js` | 任务启动、轮询、取消和设备进度展示 |
| `server/static/js/devices.js` | 设备健康、屏幕流、键盘、熔断状态展示 |
| `tests/e2e/test_web_workflows.py` | 登录、采集、发送、取消、失败重试的浏览器端到端测试 |
| `scripts/smoke/real_device_acceptance.py` | 单台真实设备验收脚本，不直接纳入自动 CI |
| `scripts/load/matrix_30_devices.py` | 30 台虚拟设备负载和公平性报告 |

---

## Phase A: Contract And Task Reliability

### Task 1: Freeze A Reproducible Baseline

**Files:**
- Modify: `pyproject.toml`
- Create: `docs/superpowers/audits/2026-06-20-baseline.md`
- Test: `tests/`

- [ ] **Step 1: Run the current test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short
```

Expected: record the exact passed/failed/skipped counts. Do not change code before the failures are listed in the baseline document.

- [ ] **Step 2: Run static and migration checks**

```powershell
.\.venv\Scripts\python.exe -m ruff check core server adapters tests cli.py
.\.venv\Scripts\python.exe -m mypy core server adapters cli.py --ignore-missing-imports
$env:THUNDER_DATABASE_URL='sqlite:///data/plan_validation.db'
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
```

Expected: Alembic reports `No new upgrade operations detected`; ruff/mypy counts are recorded even if they are not yet zero.

- [ ] **Step 3: Add explicit pytest markers**

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
addopts = "--import-mode=importlib"
markers = [
    "contract: frontend/backend API contract tests",
    "matrix: multi-device scheduling tests",
    "real_device: requires a connected Android device",
    "e2e: browser end-to-end tests",
]
```

- [ ] **Step 4: Write the baseline report**

The report must contain the exact commands, exit codes, failed test names, ruff/mypy counts, current migration head, Python version and Git commit.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml docs/superpowers/audits/2026-06-20-baseline.md
git commit -m "test: freeze matrix stabilization baseline"
```

### Task 2: Add Frontend/Backend Contract Tests

**Files:**
- Create: `tests/server/api/test_frontend_contract.py`
- Modify: `server/api/jobs.py`
- Modify: `server/api/devices.py`
- Modify: `server/api/leads.py`
- Modify: `server/api/dashboard.py`

- [ ] **Step 1: Write the failing route contract test**

```python
import pytest
from server.main import app


REQUIRED_ROUTES = {
    ("GET", "/api/dashboard/state"),
    ("GET", "/api/devices"),
    ("GET", "/api/jobs"),
    ("POST", "/api/jobs/collect/start"),
    ("POST", "/api/jobs/send/start"),
    ("POST", "/api/jobs/{job_id}/cancel"),
    ("GET", "/api/leads"),
    ("POST", "/api/leads/retry-failed"),
}


@pytest.mark.contract
def test_required_frontend_routes_exist():
    actual = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert REQUIRED_ROUTES <= actual
```

- [ ] **Step 2: Run it and confirm the baseline**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/api/test_frontend_contract.py -v
```

Expected: the route test passes; new response-contract tests added in the next step initially fail on any inconsistent field.

- [ ] **Step 3: Add response models to core UI endpoints**

Define explicit Pydantic response types instead of returning undocumented dictionaries. The minimum contracts are:

```python
class StartJobResponse(BaseModel):
    ok: bool
    job_id: str
    status: str


class CancelJobResponse(BaseModel):
    job_id: str
    status: str
    cancel_requested: bool
    released_claimed_tasks: int = 0


class LeadListResponse(BaseModel):
    leads: list[LeadSummary]
    total: int
    limit: int
    offset: int
```

Apply these with `response_model=` on their FastAPI routes.

- [ ] **Step 4: Test the serialized field names**

```python
def test_start_job_response_contract():
    schema = StartJobResponse(ok=True, job_id="job-1", status="running")
    assert schema.model_dump() == {
        "ok": True,
        "job_id": "job-1",
        "status": "running",
    }
```

- [ ] **Step 5: Run contract and existing API tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/api tests/server/test_industries.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add server/api tests/server/api/test_frontend_contract.py
git commit -m "test: enforce frontend backend API contracts"
```

### Task 3: Make Job Cancellation A Strict State Machine

**Files:**
- Create: `core/task/job_state.py`
- Modify: `server/workers.py`
- Modify: `server/api/jobs.py`
- Create: `tests/server/test_job_lifecycle.py`
- Modify: `tests/server/test_workers.py`

- [ ] **Step 1: Write state transition tests**

```python
import pytest
from core.task.job_state import JobState, transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobState.PENDING, JobState.RUNNING),
        (JobState.RUNNING, JobState.CANCELLING),
        (JobState.CANCELLING, JobState.CANCELLED),
        (JobState.RUNNING, JobState.COMPLETED),
        (JobState.RUNNING, JobState.FAILED),
    ],
)
def test_valid_job_transitions(current, target):
    assert transition(current, target) is target


def test_cancelled_job_cannot_complete():
    with pytest.raises(ValueError):
        transition(JobState.CANCELLED, JobState.COMPLETED)
```

- [ ] **Step 2: Run and confirm failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_job_lifecycle.py -v
```

Expected: import failure because `core.task.job_state` does not exist.

- [ ] **Step 3: Implement the state machine**

```python
from enum import StrEnum


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


ALLOWED = {
    JobState.PENDING: {JobState.RUNNING, JobState.CANCELLED, JobState.FAILED},
    JobState.RUNNING: {JobState.CANCELLING, JobState.COMPLETED, JobState.FAILED},
    JobState.CANCELLING: {JobState.CANCELLED, JobState.FAILED},
    JobState.CANCELLED: set(),
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
}


def transition(current: JobState, target: JobState) -> JobState:
    if target not in ALLOWED[current]:
        raise ValueError(f"illegal job transition: {current} -> {target}")
    return target
```

- [ ] **Step 4: Route every worker status update through the state machine**

In `server/workers.py`, centralize DB updates in `_transition_job(job_id, user_id, target, patch=None)`. Cancellation must set the stop event, release the job's claimed tasks, force-stop only that job's active apps, and finish as `cancelled` after workers exit or the grace timeout expires.

- [ ] **Step 5: Add cancellation regression tests**

Test all of these assertions:

```python
assert cancel_job(job_id, user_id)["status"] in {"cancelling", "cancelled"}
assert get_job_status(job_id, user_id)["cancel_requested"] is True
assert claimed_tasks_for_job(job_id) == 0
assert get_job_status(job_id, user_id)["status"] != "completed"
```

- [ ] **Step 6: Run lifecycle tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_job_lifecycle.py tests/server/test_workers.py -q
```

Expected: all tests pass and no worker thread remains alive after the test fixture closes.

- [ ] **Step 7: Commit**

```powershell
git add core/task/job_state.py server/workers.py server/api/jobs.py tests/server
git commit -m "fix: enforce cancellable job lifecycle"
```

---

## Phase B: Agent And Device Execution Closure

### Task 4: Verify Send Success From Perception Evidence

**Files:**
- Create: `core/task/send_verifier.py`
- Modify: `core/task/worker.py`
- Modify: `core/task/runner.py`
- Modify: `core/agent/perception.py`
- Create: `tests/core/task/test_send_verifier.py`

- [ ] **Step 1: Write pure verifier tests**

```python
from core.task.send_verifier import SendEvidence, verify_send


def test_send_requires_message_bubble_or_success_signal():
    evidence = SendEvidence(
        before_screen="profile",
        after_screen="conversation",
        ocr_text="你好，想了解一下",
        ui_texts=["你好，想了解一下"],
        blocker="",
    )
    result = verify_send("你好，想了解一下", evidence)
    assert result.ok is True


def test_login_screen_is_not_success():
    evidence = SendEvidence(
        before_screen="profile",
        after_screen="login_required",
        ocr_text="登录后继续",
        ui_texts=[],
        blocker="login_required",
    )
    assert verify_send("测试消息", evidence).ok is False
```

- [ ] **Step 2: Run and confirm failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_send_verifier.py -v
```

Expected: import failure because `send_verifier.py` does not exist.

- [ ] **Step 3: Implement deterministic verification**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class SendEvidence:
    before_screen: str
    after_screen: str
    ocr_text: str
    ui_texts: list[str]
    blocker: str = ""


@dataclass(frozen=True)
class SendVerification:
    ok: bool
    reason: str
    confidence: float


def verify_send(message: str, evidence: SendEvidence) -> SendVerification:
    if evidence.blocker:
        return SendVerification(False, evidence.blocker, 1.0)
    normalized = "".join(message.split())
    haystack = "".join((evidence.ocr_text + "".join(evidence.ui_texts)).split())
    if evidence.after_screen == "conversation" and normalized and normalized in haystack:
        return SendVerification(True, "message_visible", 0.95)
    return SendVerification(False, "unconfirmed_send", 0.4)
```

- [ ] **Step 4: Integrate it before queue completion**

`core/task/worker.py` must mark a task `done` only after `verify_send(...).ok` is true. `unconfirmed_send` must go to retry with screenshot path, OCR text, screen state and execution log payload; it must never be counted as sent.

- [ ] **Step 5: Persist evidence**

Use the existing `ScreenSnapshot` and `ExecutionLog` tables. The execution payload must include:

```python
{
    "verification_reason": result.reason,
    "verification_confidence": result.confidence,
    "before_screen": evidence.before_screen,
    "after_screen": evidence.after_screen,
    "screenshot_path": observation.screenshot_path,
}
```

- [ ] **Step 6: Run verifier and worker tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_send_verifier.py tests/core/task -q
```

Expected: all tests pass; no test can mark a task done without confirmation evidence.

- [ ] **Step 7: Commit**

```powershell
git add core/task core/agent/perception.py tests/core/task
git commit -m "feat: verify private message delivery from UI evidence"
```

### Task 5: Prove 30-Device Scheduling Correctness

**Files:**
- Modify: `core/task/scheduler.py`
- Modify: `core/device/supervisor.py`
- Modify: `core/task/worker.py`
- Create: `tests/core/task/test_matrix_30_devices.py`
- Create: `scripts/load/matrix_30_devices.py`

- [ ] **Step 1: Write the 30-device claim test**

```python
import concurrent.futures
import pytest


@pytest.mark.matrix
def test_30_devices_never_claim_the_same_task(scheduler_factory):
    scheduler = scheduler_factory(task_count=300)

    def claim(device_no):
        return scheduler.claim_next(f"device-{device_no}", job_id="job-30")

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
        claims = list(pool.map(claim, range(30)))

    task_ids = [claim.task_id for claim in claims if claim]
    assert len(task_ids) == 30
    assert len(set(task_ids)) == 30
```

- [ ] **Step 2: Add quota, cooldown and cancellation tests**

Required assertions:

```python
assert total_reserved <= industry.global_daily_limit
assert claims_by_device["cooldown-device"] == 0
assert scheduler.claimed_count(job_id="cancelled-job") == 0
assert max(claims_by_device.values()) - min(claims_by_device.values()) <= 1
```

- [ ] **Step 3: Run and confirm any race failures**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_matrix_30_devices.py -v --count=10
```

Expected: fail if claim/reservation is not atomic. Install `pytest-repeat` in the dev dependency group if `--count` is unavailable.

- [ ] **Step 4: Make claim and quota reservation one transaction**

For SQLite use `BEGIN IMMEDIATE`; for PostgreSQL use `SELECT ... FOR UPDATE SKIP LOCKED`. Every claim must bind `task_id`, `job_id`, `device_id`, `claim_token` and `claimed_at`. Every completion/retry/release update must include the same token and job guard.

- [ ] **Step 5: Add a load report script**

`scripts/load/matrix_30_devices.py` must print JSON containing:

```json
{
  "devices": 30,
  "tasks": 3000,
  "duplicate_claims": 0,
  "quota_violations": 0,
  "cancel_release_seconds": 0.0,
  "fairness_spread": 0
}
```

- [ ] **Step 6: Run matrix tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_matrix_30_devices.py tests/core/task/test_scheduler.py -q
.\.venv\Scripts\python.exe scripts/load/matrix_30_devices.py --devices 30 --tasks 3000
```

Acceptance: zero duplicate claims, zero quota violations, cancellation releases claims within 5 seconds, fairness spread no greater than 2 tasks.

- [ ] **Step 7: Commit**

```powershell
git add core/task core/device/supervisor.py tests/core/task scripts/load
git commit -m "test: prove scheduler safety for 30 devices"
```

---

## Phase C: UI Observability And Release

### Task 6: Modularize The Web UI Around The API Contract

**Files:**
- Create: `server/static/js/api.js`
- Create: `server/static/js/jobs.js`
- Create: `server/static/js/devices.js`
- Modify: `server/static/index.html`
- Create: `tests/e2e/test_web_workflows.py`

- [ ] **Step 1: Write browser workflow tests**

```python
import pytest


@pytest.mark.e2e
def test_cancel_button_reaches_cancelled_state(page, live_server, seeded_user):
    page.goto(live_server)
    page.get_by_label("用户名").fill(seeded_user.username)
    page.get_by_label("密码").fill(seeded_user.password)
    page.get_by_role("button", name="立即登录").click()
    page.get_by_role("button", name="执行记录").click()
    page.get_by_role("button", name="取消任务").first.click()
    page.get_by_text("已取消").wait_for(timeout=10_000)
```

- [ ] **Step 2: Run and confirm failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_web_workflows.py -v
```

Expected: fail until Playwright fixtures and stable accessible labels are added.

- [ ] **Step 3: Extract the API client**

`server/static/js/api.js` must export:

```javascript
export async function apiFetch(endpoint, options = {}) {
    const token = localStorage.getItem('thunder_token') || '';
    const headers = new Headers(options.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body && !(options.body instanceof FormData)) {
        headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(endpoint, { ...options, headers });
    if (response.status === 401) {
        localStorage.removeItem('thunder_token');
        window.location.assign('/');
        throw new Error('登录已过期');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `请求失败 (${response.status})`);
    return data;
}
```

- [ ] **Step 4: Extract task and device controllers**

`jobs.js` owns start/poll/cancel and must stop polling terminal states. `devices.js` owns scan, health, keyboard preparation, screen stream and manual controls. `index.html` retains templates and high-level navigation only.

- [ ] **Step 5: Expose missing operational views**

Add UI access for:

- `/api/jobs/{job_id}/devices`: per-device task progress and final reason.
- `/api/dashboard/execution`: latest screen, blocker and action evidence.
- `/api/devices/{device_id}/health`: online, keyboard, cooldown and failure count.
- `/api/jobs/{job_id}/cancel`: canonical cancellation endpoint; keep `/api/tasks/status/...` only as compatibility.

- [ ] **Step 6: Run browser and API tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_web_workflows.py tests/server/api/test_frontend_contract.py -q
```

Acceptance: login, collect start, send start, cancel, failed retry and device health workflows pass at 1440x900 and 390x844 viewports.

- [ ] **Step 7: Commit**

```powershell
git add server/static tests/e2e tests/server/api/test_frontend_contract.py
git commit -m "refactor: align web UI with matrix APIs"
```

### Task 7: Add Real-Device Acceptance And Operational Evidence

**Files:**
- Create: `scripts/smoke/real_device_acceptance.py`
- Create: `docs/superpowers/sops/real-device-acceptance.md`
- Modify: `server/logging_config.py`
- Modify: `server/api/dashboard.py`

- [ ] **Step 1: Implement a dry-run acceptance command**

The script must accept:

```powershell
.\.venv\Scripts\python.exe scripts/smoke/real_device_acceptance.py `
  --serial DEVICE_SERIAL `
  --industry INDUSTRY_SLUG `
  --target TEST_ACCOUNT `
  --message "验收测试，请忽略" `
  --dry-run
```

Dry-run stops before the final send action but must capture device health, keyboard state, profile match, screenshot, OCR, UI tree and planned action.

- [ ] **Step 2: Add explicit live-send protection**

The final send requires all three flags:

```powershell
--live-send --confirm-target TEST_ACCOUNT --max-sends 1
```

The script must refuse `--live-send` when the target does not exactly match the observed profile identifier.

- [ ] **Step 3: Emit one correlation ID across logs**

Every acceptance run must include `job_id`, `device_id`, `task_id`, `claim_token` and `correlation_id` in structured logs and dashboard execution records.

- [ ] **Step 4: Run one dry-run per supported device class**

Acceptance evidence must include the command, device model, Android version, ADB keyboard status, screenshots, inferred screens and final dry-run result.

- [ ] **Step 5: Run one controlled live send**

Acceptance: exactly one test message appears on the intended test account, task status becomes `done` only after visual confirmation, and cancel during a second prepared run reaches `cancelled` within 20 seconds.

- [ ] **Step 6: Commit**

```powershell
git add scripts/smoke/real_device_acceptance.py docs/superpowers/sops/real-device-acceptance.md server/logging_config.py server/api/dashboard.py
git commit -m "test: add guarded real device acceptance workflow"
```

### Task 8: Production Release Gate

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Dockerfile.server`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `PROJECT_STRUCTURE.md`

- [ ] **Step 1: Add CI stages**

The workflow must run, in order:

```yaml
- run: python -m pytest tests/server tests/core tests/adapters -q
- run: python -m ruff check core server adapters tests cli.py
- run: python -m mypy core server adapters cli.py --ignore-missing-imports
- run: alembic upgrade head
- run: alembic check
```

- [ ] **Step 2: Define release thresholds**

A release is blocked unless:

- Core/API automated tests have zero failures.
- Frontend contract coverage is 100% for UI-called routes and methods.
- Matrix test has zero duplicate claims and quota violations.
- Cancellation releases claims within 5 seconds in simulation and 20 seconds on a real device.
- A sent task has screenshot/UI evidence and a non-empty verification reason.
- No device in `isolated`, `offline`, `keyboard_error` or active cooldown is scheduled.

- [ ] **Step 3: Validate production configuration**

Production startup must fail when `THUNDER_SECRET_KEY`, database URL or allowed CORS origins are absent. Redis/PostgreSQL adapters must be health-checked before workers accept jobs.

- [ ] **Step 4: Run the full release command set**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short
.\.venv\Scripts\python.exe -m ruff check core server adapters tests cli.py
.\.venv\Scripts\python.exe -m mypy core server adapters cli.py --ignore-missing-imports
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
```

Expected: all commands exit 0.

- [ ] **Step 5: Update operations documentation**

Document start/stop commands, port 8000, Redis/PostgreSQL requirements, ADB device onboarding, ADB Keyboard preparation, backup/restore, cancellation semantics and the real-device acceptance checklist.

- [ ] **Step 6: Commit**

```powershell
git add .github/workflows/ci.yml Dockerfile.server docker-compose.yml README.md PROJECT_STRUCTURE.md
git commit -m "chore: establish production release gate"
```

---

## Execution Order And Milestones

| Milestone | Tasks | Exit condition |
|---|---|---|
| M1 Contract stable | 1-2 | UI-called API route/method coverage 100%; response models fixed |
| M2 Cancellation reliable | 3 | cancelled jobs cannot later become completed; claims released |
| M3 Agent send closure | 4 | no task is counted sent without UI evidence |
| M4 Matrix ready | 5 | 30-device simulation passes duplicate/quota/fairness gates |
| M5 UI operational | 6 | operator can inspect, cancel and diagnose each device from Web UI |
| M6 Real-device accepted | 7 | dry-run and one controlled live send have complete evidence |
| M7 Production ready | 8 | tests, lint, type, migration and configuration gates all pass |

## Self-Review

### Spec Coverage

- Frontend/backend alignment: Tasks 2 and 6.
- Cancellation and task lifecycle: Task 3.
- Screenshot/OCR/UI-driven decisions: Task 4.
- 30-device matrix scheduling: Task 5.
- Real phone validation: Task 7.
- Production deployment and maintenance: Task 8.

### Placeholder Scan

- No placeholder markers remain.
- Every implementation task includes exact files, commands, expected outcomes and acceptance criteria.

### Type Consistency

- Job states consistently use `pending/running/cancelling/cancelled/completed/failed`.
- Task ownership consistently uses `task_id/job_id/device_id/claim_token`.
- Send verification consistently returns `SendVerification(ok, reason, confidence)`.
