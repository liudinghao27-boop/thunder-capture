# Phase 8 Web UI And Backend Logic Audit

## Scope

Reviewed whether the Phase 8 backend changes are visible and usable from the Web UI:

- Job list and job detail execution evidence.
- Device acceptance dry-run/live-send evidence.
- Agent decision fields: `page_state`, `next_action`, `confidence`, `blocker`, `reason`, `screenshot`.
- Send verification fields: `ok`, `reason`, `confidence`, `screenshot_path`.

## Findings

### 1. Backend Trace Data Was Available But Job List Did Not Return It

Status: fixed.

`/api/jobs/{job_id}` exposed `latest_execution`, but `/api/jobs` did not return it even though the endpoint already queried it internally for normalization. This meant the Web UI task list could not show Agent Trace without extra per-row detail calls.

Fix:

- `JobSummary` now includes `latest_execution` and `latest_snapshot`.
- `/api/jobs` returns `latest_execution.agent_decision` and `latest_execution.send_verification`.

### 2. Web UI Did Not Render Agent Decision Evidence

Status: fixed.

The backend returned Agent evidence, but `server/static/index.html` did not read:

- `latest_execution.agent_decision`
- `latest_execution.send_verification`
- `before_decision`
- `after_decision`
- `send_verification`

Fix:

- Added `renderAgentDecisionTrace()`.
- Job rows now render page state, next action, confidence, blocker, reason, and screenshot path.

### 3. Device Acceptance API Returned Evidence But UI Had No Direct Entry

Status: fixed.

`DeviceApi.dryRun()` and `DeviceApi.liveSend()` existed, but the device table had no visible controls wired to them.

Fix:

- Added device row actions for dry-run acceptance and guarded live-send acceptance.
- Added `runDeviceAcceptance()` to collect target/message and call the correct API.
- Added `summarizeAcceptanceTrace()` so the operator sees the returned decision/verification summary.

### 4. Device Acceptance Used Browser Prompts Instead Of A Product Flow

Status: fixed.

The first implementation worked but forced the operator through browser prompt dialogs for project, target, and message input. This is not suitable for repeated matrix operations or guarded live-send confirmation.

Fix:

- Added an in-page device acceptance modal.
- Dry-run and live-send now share the same structured form.
- Live-send keeps an explicit confirmation step before executing.
- Acceptance results now render returned Agent decision, send verification, report path, and screenshot evidence in the modal.

### 5. Screenshot Evidence Was Not Directly Inspectable

Status: fixed.

Screenshot evidence paths were visible, but not actionable from the Web UI.

Fix:

- Added `GET /api/devices/evidence/file`.
- The endpoint only serves files under `data/acceptance`.
- The Web UI fetches screenshots with the existing authenticated request helper and opens a temporary preview URL.

### 6. Task Rows Needed A Full Evidence Review Path

Status: fixed.

Inline trace is useful for quick scanning, but operators need a full review path after a send task finishes or fails.

Fix:

- Added a job-row evidence action.
- Added a right-side task evidence drawer.
- The drawer loads `/api/agent/execution-logs?job_id=...`.
- Each timeline entry shows action, status, device, time, latency, Agent decision, verification result, blocker, and screenshot link.
- Added a structured response model and frontend route contract for the execution logs endpoint.

## Product Design Assessment

The flow is now more aligned with operator expectations:

- A user can start device acceptance from the device row instead of guessing an API route.
- A user can inspect why a send did or did not succeed from the task list.
- The system now exposes evidence in operational language: page state, next action, verification result, blocker, and screenshot path.
- A user can complete acceptance without leaving the page or manually finding local screenshot files.
- A user can open a completed task and review the execution evidence chain without searching logs manually.

## Remaining UX Risks

- The legacy single-file Web UI still has mixed historical encoding in some labels. This does not block the backend/frontend logic contract, but should be cleaned during the larger UI restructuring pass.
- The evidence drawer is read-only. Future matrix operations should add filters by device, blocker type, and failed/sent status once 30-device execution logs become dense.

## Verification

Covered by:

- `tests/server/api/test_execution_views.py`
- `tests/server/api/test_static_modules.py`
- `tests/server/api/test_devices_evidence.py`
- `tests/server/api/test_frontend_contract.py`
- `tests/scripts/test_real_device_acceptance.py`
