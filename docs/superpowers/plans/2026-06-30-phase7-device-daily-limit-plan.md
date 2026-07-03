# Phase 7 Matrix Send Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Phase 7 matrix send-limit, cooldown, isolation, and dashboard visibility contract so each device stops claiming leads after configured caps, while cooling down, or after high-risk blocker events, and operators can see remaining capacity from the dashboard API.

**Architecture:** Keep `MatrixTaskScheduler` as the queue claim boundary for quotas and `DeviceSupervisor` as the device readiness boundary. Add device-level daily and hourly checks against `ConsumerState` before task claim, then update the same state when a claimed task is successfully marked done. `DeviceSupervisor.preflight()` blocks devices whose `cooldown_until` is still active before ADB health checks or task claims. `DeviceWorker` feeds failed send results through `RiskManager`; high-risk blockers isolate the device and stop the loop.

**Tech Stack:** Python 3.14, SQLAlchemy, pytest, existing `TaskQueue` and `ConsumerState` models.

---

## File Structure

- `core/task/scheduler.py`
  - Owns task claiming, quota reservation, task commit/release, and device send counters.
- `core/task/worker.py`
  - Owns per-device worker initialization and passes device send limits into the scheduler.
- `core/device/supervisor.py`
  - Owns runtime device readiness gates, failure status, cooldown state, and preflight decisions.
- `tests/core/task/test_scheduler.py`
  - Verifies device daily limit and successful send counter updates.
- `tests/core/task/test_worker_abtest.py`
  - Verifies worker forwards configured send limits into the scheduler.
- `tests/core/device/test_supervisor.py`
  - Verifies cooldown preflight behavior.

---

### Task 1: Device Daily Limit Claim Gate

**Files:**
- Modify: `core/task/scheduler.py`
- Test: `tests/core/task/test_scheduler.py`

- [x] **Step 1: Add failing test**

Add a test that seeds `ConsumerState(consumer_id="d1", daily_sent=2, daily_limit=2, last_sent_date=today)` and one pending task, then calls:

```python
MatrixTaskScheduler(
    industry_slug="test",
    owner_user_id="u1",
    device_daily_limit=2,
).claim_for_device("d1")
```

Expected result:

```python
assert result.task is None
assert result.reason == "device_daily_limit_reached"
```

- [x] **Step 2: Implement claim gate**

Add `device_daily_limit` to `MatrixTaskScheduler.__init__()`, then check `ConsumerState` for the current UTC day before reserving global/industry quota or claiming a task.

- [x] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_scheduler.py::test_claim_respects_device_daily_limit -q
```

Expected: PASS.

---

### Task 2: Successful Send Counter

**Files:**
- Modify: `core/task/scheduler.py`
- Test: `tests/core/task/test_scheduler.py`

- [x] **Step 1: Add failing test**

Seed a claimed task and `ConsumerState(consumer_id="d1", daily_sent=1, last_sent_date=today, total_sent=4)`.

After:

```python
scheduler.mark_task_done(task_id, "d1", ai_reply="ok", claim_token="token-1")
```

Expected:

```python
assert state.daily_sent == 2
assert state.total_sent == 5
assert state.last_sent_date == today
```

- [x] **Step 2: Implement counter update**

When `mark_task_done()` succeeds, update or create `ConsumerState`, reset `daily_sent` when the day changes, increment `daily_sent` and `total_sent`, and preserve quota commit behavior.

- [x] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_scheduler.py::test_mark_task_done_increments_device_daily_sent -q
```

Expected: PASS.

---

### Task 3: Worker Wiring

**Files:**
- Modify: `core/task/worker.py`
- Test: `tests/core/task/test_worker_abtest.py`

- [x] **Step 1: Add worker contract assertion**

Update the worker scheduler wiring test to assert:

```python
assert worker._scheduler.device_daily_limit == 7
```

- [x] **Step 2: Pass limit into scheduler**

Add:

```python
device_daily_limit=int(self.daily_limit or 0)
```

to the `MatrixTaskScheduler` initialization inside `DeviceWorker`.

- [x] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_worker_abtest.py -q
```

Expected: PASS.

---

### Task 4: Device Hourly Limit Claim Gate

**Files:**
- Modify: `core/task/scheduler.py`
- Test: `tests/core/task/test_scheduler.py`

- [x] **Step 1: Add failing tests**

Add tests for:

```python
MatrixTaskScheduler(
    industry_slug="test",
    owner_user_id="u1",
    hourly_send_limit=2,
).claim_for_device("d1")
```

Expected when `ConsumerState.wave_sent == 2` and `rate_limited_at` is within one hour:

```python
assert result.task is None
assert result.reason == "device_hourly_limit_reached"
```

Expected when `rate_limited_at` is older than one hour:

```python
assert result.ok is True
assert state.wave_sent == 0
assert state.rate_limited_at == ""
```

- [x] **Step 2: Implement hourly window**

Use `ConsumerState.rate_limited_at` as the current hour window start and `ConsumerState.wave_sent` as the number of successful sends inside that window. Reset the window automatically after one hour.

- [x] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_scheduler.py::test_claim_respects_device_hourly_limit tests/core/task/test_scheduler.py::test_claim_resets_expired_device_hourly_window tests/core/task/test_scheduler.py::test_mark_task_done_increments_device_hourly_window -q
```

Expected: PASS.

---

### Task 5: Hourly Limit Worker Wiring

**Files:**
- Modify: `core/task/worker.py`
- Test: `tests/core/task/test_worker_abtest.py`
- Test: `tests/core/task/test_worker_compliance.py`

- [x] **Step 1: Pass hourly limit to scheduler**

Add:

```python
hourly_send_limit=int(getattr(self.industry, "hourly_send_limit", 0) or 0)
```

to `DeviceWorker` scheduler initialization.

- [x] **Step 2: Preserve Celery path**

Include `hourly_send_limit` in Celery `task_data` so async execution receives the same limit.

- [x] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_worker_abtest.py::test_worker_passes_send_limits_to_scheduler tests/core/task/test_worker_compliance.py::test_run_senders_includes_scheduler_limits_in_celery_task_data -q
```

Expected: PASS.

---

### Task 6: Device Cooldown Preflight Gate

**Files:**
- Modify: `core/device/supervisor.py`
- Test: `tests/core/device/test_supervisor.py`

- [x] **Step 1: Add failing tests**

Add tests for active and expired cooldown:

```python
gate = DeviceSupervisor(user_id="u1", industry_slug="test").preflight(
    device_id="d1",
    adb_serial="serial-1",
    job_id="job-1",
)
```

Expected when `Device.cooldown_until` is in the future:

```python
assert gate.ok is False
assert gate.status == "cooldown"
assert "cooldown_until" in gate.reason
```

Expected when `Device.cooldown_until` is expired:

```python
assert gate.ok is True
assert gate.status == "running"
assert device.cooldown_until is None
```

- [x] **Step 2: Implement preflight gate**

Check persisted device cooldown before ADB health checks. Active cooldown returns `DeviceGate(False, "cooldown", ...)`. Expired cooldown clears `cooldown_until`, returns the device to `idle`, and then continues normal health preflight.

- [x] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/device/test_supervisor.py -q
```

Expected: PASS.

---

### Task 7: Risk Blocker Device Isolation

**Files:**
- Modify: `core/task/worker.py`
- Test: `tests/core/task/test_worker_abtest.py`
- Test: `tests/core/device/test_supervisor.py`

- [x] **Step 1: Add failing worker test**

Simulate a failed send result:

```python
mock_runner.run_douyin_dm.return_value = MagicMock(
    ok=False,
    status="blocked",
    message="Blocked before execution: risk_control",
)
```

Expected:

```python
assert summary["status"] == "isolated"
assert worker._supervisor.mark_failure.call_args.kwargs["status"] == "isolated"
assert worker._scheduler.claim_for_device.call_count == 1
```

- [x] **Step 2: Route send failures through RiskManager**

For non-ok execution results and exceptions, call `RiskManager.assess_action_result()`. If the decision is `isolate`, mark the device `isolated`, update the summary, and break the send loop. If the decision is `cooldown`, mark device cooldown and break.

- [x] **Step 3: Lock terminal isolation behavior**

Add a supervisor test proving `mark_finished(... status="idle")` does not reopen an `isolated` device.

- [x] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/task/test_worker_abtest.py::test_worker_isolates_device_on_risk_blocker_result tests/core/device/test_supervisor.py -q
```

Expected: PASS.

---

### Task 8: Worker Import Stability

**Files:**
- Modify: `core/task/worker.py`
- Test: `tests/server/test_workers.py`

- [x] **Step 1: Identify regression signal**

Running a focused server worker test exposed intermittent import-time memory pressure while importing the `openai` package through `core.task.worker`.

- [x] **Step 2: Move heavy import to lazy path**

Move:

```python
from openai import OpenAI
```

from module import time into `_get_reply_client()`, so worker module import does not load the OpenAI client stack unless reply generation needs it.

- [x] **Step 3: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/test_workers.py::test_run_senders_returns_cancelled_when_device_thread_does_not_exit -q
```

Expected: PASS.

---

### Task 9: Dashboard Device Capacity Fields

**Files:**
- Modify: `server/api/dashboard.py`
- Test: `tests/server/api/test_dashboard.py`

- [x] **Step 1: Add failing dashboard API test**

Seed one device and one matching `ConsumerState`, then call:

```python
client.get("/api/dashboard/state")
```

Expected each device row includes:

```python
assert dev["daily_limit"] == 10
assert dev["daily_sent"] == 4
assert dev["daily_remaining"] == 6
assert dev["hourly_sent"] == 2
assert dev["cooldown_active"] is True
assert isinstance(dev["cooldown_remaining_seconds"], int)
```

- [x] **Step 2: Extend DashboardDevice response contract**

Add daily quota, hourly window, and cooldown fields to `DashboardDevice`.

- [x] **Step 3: Aggregate ConsumerState in dashboard state**

Join device rows with `ConsumerState` by `consumer_id == device.id` and compute `daily_remaining` plus cooldown remaining seconds.

- [x] **Step 4: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server/api/test_dashboard.py::test_dashboard_state_includes_device_capacity_and_cooldown -q
```

Expected: PASS.

---

## Regression

- [x] `.\.venv\Scripts\python.exe -m pytest tests/core/task/test_scheduler.py tests/core/task/test_matrix_30_devices.py tests/core/task/test_worker_abtest.py -q`
- [x] `.\.venv\Scripts\python.exe -m pytest tests/core/task/test_worker_compliance.py tests/server/test_workers.py -q`
- [x] `.\.venv\Scripts\python.exe -m pytest tests/core/device/test_supervisor.py -q`
- [x] `.\.venv\Scripts\python.exe -m pytest tests/core/task/test_worker_abtest.py::test_worker_isolates_device_on_risk_blocker_result -q`
- [x] `.\.venv\Scripts\python.exe -m pytest tests/server/test_workers.py::test_run_senders_returns_cancelled_when_device_thread_does_not_exit -q`
- [x] `.\.venv\Scripts\python.exe -m pytest tests/server/api/test_dashboard.py::test_dashboard_state_includes_device_capacity_and_cooldown -q`
- [x] `.\.venv\Scripts\python.exe -m compileall core server adapters -q`

## Remaining Phase 7 Work

- Frontend devices table can be enhanced later to show the same capacity fields from `/api/devices`; Phase 7 dashboard API contract is complete.
