# Phase 8 Screenshot/OCR/UI Decision Plan

## Goal

Build a stable first version of screenshot/OCR/UI-parse driven Agent execution for real-device matrix sending.

## Completed In This Slice

- Added `AgentDecision` as the normalized decision payload.
- Added `core.agent.decision.decide_next_action()`.
- Connected `TaskGraphRunner` observation logs to decisions.
- Added blocked preflight return payload with `decision`.
- Added post-send `agent_decisions.before/after` payload.
- Added UIParser coverage for English/OCR login expiry and risk-control text.
- Added API-level decision evidence exposure for job detail, Agent logs, and execution monitor.
- Added Douyin-specific state rules for search results, profile DM readiness, DM unavailable, disabled chat input, and sent message bubbles.
- Added recovery policy for action mapping and preflight unknown-screen retries before execution.
- Added real-device acceptance evidence summary fields and API response exposure.
- Added Web UI trace display for job execution evidence and device acceptance entrypoints.
- Added in-page device acceptance modal and authenticated evidence screenshot preview.
- Added a Web UI job evidence drawer backed by Agent execution logs.

## Remaining Tasks

### Task 1: Persist Decisions As First-Class Evidence

Status: completed in the first follow-up slice.

- Add decision fields to screen snapshot or execution log views.
- Ensure Web UI can display decision state, reason, screenshot, and blocker.
- Keep existing DB compatibility by storing JSON in payload first unless schema migration is needed.

### Task 2: Add Platform-Specific State Rules

Status: completed for the first Douyin rule set.

- Expand Douyin state rules for:
  - profile DM button available
  - DM button unavailable
  - search result list
  - chat input disabled
  - sent message bubble visible
- Add independent parser fixtures for each state.

### Task 3: Add Retry/Recovery Policy

Status: completed for the first preflight recovery loop.

- Map decisions to recovery actions:
  - `launcher/open_app`
  - `search/search_target`
  - `profile/open_chat`
  - `blocked/stop`
  - `unknown/observe`
- Set max observe retries before marking `ui_unknown`.

### Task 4: Add Real-Device Evidence Acceptance

Status: completed.

- Extend the real-device smoke script to print:
  - before decision
  - after decision
  - send verification
  - screenshot path
- Acceptance requires visible evidence for each failed or blocked send.

### Task 5: Web UI Trace Display

Status: completed.

- Add a task detail panel for:
  - current page state
  - next action
  - confidence
  - blocker
  - reason
  - screenshot link

### Task 6: Productized Device Acceptance Flow

Status: completed.

- Replace browser prompt-based acceptance with an in-page modal.
- Support dry-run and guarded live-send acceptance from the device row.
- Render returned Agent decision and send verification evidence in the modal result.
- Add an authenticated evidence file endpoint for acceptance screenshots.

### Task 7: Job Evidence Timeline

Status: completed.

- Add a job-row evidence action for post-run review.
- Add a right-side evidence drawer that loads `/api/agent/execution-logs`.
- Render each execution log with action, status, device, timestamp, latency, Agent decision, verification reason, blocker, and screenshot link.
- Add a response model to the execution log API so Web UI dependencies are covered by contract tests.

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core\agent\test_decision.py tests\core\task\test_runner_send_verification.py tests\core\test_ui_parser.py -q
.\.venv\Scripts\python.exe -m pytest tests\core\task\test_send_verifier.py tests\core\agent\test_perception.py -q
.\.venv\Scripts\python.exe -m pytest tests\server\api\test_static_modules.py tests\server\api\test_devices_evidence.py -q
.\.venv\Scripts\python.exe -m pytest tests\server\api\test_frontend_contract.py tests\server\api\test_execution_views.py -q
.\.venv\Scripts\python.exe -m compileall core server adapters -q
```
