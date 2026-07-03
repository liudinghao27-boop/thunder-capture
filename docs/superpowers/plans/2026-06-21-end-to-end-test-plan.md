# Thunder Capture End-to-End Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用自动化、浏览器、单台真实手机和分级矩阵测试证明采集、筛选、发送、取消、失败恢复及30设备调度能够稳定闭环。

**Architecture:** 测试按风险从低到高分层执行。先验证代码、数据库和 API 契约，再验证 Web UI；随后用虚拟设备证明并发正确性，最后使用专用测试账号进行 1→5→10→30 台真实设备放量。任何阶段失败都停止进入下一阶段，并保留 job、device、task、截图和日志证据。

**Tech Stack:** pytest, FastAPI TestClient, Ruff, mypy, Alembic, Browser/Playwright, ADB, OCR/UI XML, SQLite/PostgreSQL, Celery/Redis

---

## Test Data And Safety Rules

测试前准备以下专用数据，不使用真实客户线索：

| Item | Required value |
|---|---|
| Test user | 独立 QA 用户，用户名通过 `THUNDER_QA_USERNAME` 提供 |
| Test password | 通过 `THUNDER_QA_PASSWORD` 提供，不写入代码和文档 |
| Industry | `qa-douyin-matrix` |
| Target account | 专门接收测试私信的抖音测试账号 |
| Keyword | 低风险、可人工核对的测试关键词 |
| Live message | `矩阵验收测试-YYYYMMDD-HHMM，请忽略` |
| Maximum live sends | 单机阶段 1 条；5/10/30 台阶段每台最多 1 条 |

强制安全规则：

1. 未通过 dry-run 不允许真实点击发送。
2. 目标账号必须与 UI 识别结果精确匹配。
3. 真实测试只向专用测试账号发送。
4. 验证登录、验证码、风控、隐私限制时立即停止该设备。
5. 每个阶段开始前确认“取消任务”可用。
6. 30 台放量前必须通过 1、5、10 台三个阶段。

测试证据统一保存到忽略目录：

```text
logs/qa/<run-id>/
  environment.txt
  pytest.txt
  api-contract.txt
  browser-console.txt
  jobs.json
  devices.json
  screenshots/
  adb/
  acceptance.json
```

---

## Task 1: Freeze Environment And Backup Runtime Data

**Files:**
- Read: `.env`
- Read: `server/config.py`
- Read: `docker-compose.yml`
- Output: `logs/qa/<run-id>/environment.txt`
- Backup: `data/thunder.db`

- [ ] **Step 1: Stop the current service**

```powershell
.\stop_system.bat
```

Expected: port `8000` no longer has a listening process.

- [ ] **Step 2: Create the run directory**

```powershell
$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
$qaDir = Join-Path (Resolve-Path .) "logs\qa\$runId"
New-Item -ItemType Directory -Force -Path "$qaDir\screenshots", "$qaDir\adb" | Out-Null
```

Expected: the run directory and both subdirectories exist.

- [ ] **Step 3: Back up SQLite runtime data**

```powershell
Copy-Item data\thunder.db "$qaDir\thunder-before.db" -Force
```

Expected: backup file size is greater than zero. If PostgreSQL is active, use `pg_dump` instead and record the command in `environment.txt`.

- [ ] **Step 4: Record environment versions**

```powershell
@(
  ".NET/OS: $([System.Environment]::OSVersion.VersionString)"
  "Python: $(& .\.venv\Scripts\python.exe --version)"
  "Git: $(git rev-parse HEAD)"
  "Branch: $(git branch --show-current)"
  "ADB: $(adb version | Select-Object -First 1)"
) | Set-Content "$qaDir\environment.txt" -Encoding utf8
```

Expected: all five values are present. Missing ADB blocks real-device phases but not automated phases.

- [ ] **Step 5: Verify no production credentials are copied into evidence**

```powershell
Select-String -Path "$qaDir\*" -Pattern 'sk-|Bearer |api_key|password' -SimpleMatch
```

Expected: no matches.

---

## Task 2: Run The Automated Release Baseline

**Files:**
- Test: `tests/`
- Test: `tests/server/api/test_frontend_contract.py`
- Test: `tests/server/api/test_static_modules.py`
- Test: `tests/core/task/test_send_verifier.py`
- Test: `tests/core/task/test_matrix_30_devices.py`

- [ ] **Step 1: Configure a writable pytest temp directory**

```powershell
$tempRoot = Join-Path (Resolve-Path .) 'tmp\pytest-release'
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
```

Expected: pytest does not use the restricted Windows system temp directory.

- [ ] **Step 2: Run the full Python suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short `
  -p no:cacheprovider --basetemp "$tempRoot\run" 2>&1 | Tee-Object "$qaDir\pytest.txt"
```

Expected: exit code `0`, zero failures and zero errors. Warnings must be listed separately; unawaited coroutine warnings fail release review.

- [ ] **Step 3: Run API and static UI contracts separately**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\server\api\test_frontend_contract.py `
  tests\server\api\test_static_modules.py -v `
  -p no:cacheprovider --basetemp "$tempRoot\contract" `
  2>&1 | Tee-Object "$qaDir\api-contract.txt"
```

Expected: every front-end critical route exists, core responses publish schemas, and `api.js/jobs.js/devices.js` load before the inline app.

- [ ] **Step 4: Run code quality gates**

```powershell
.\.venv\Scripts\python.exe -m ruff check core server adapters tests cli.py
.\.venv\Scripts\python.exe -m mypy core server adapters cli.py --ignore-missing-imports
```

Expected: both commands exit `0`.

- [ ] **Step 5: Validate migrations on an empty database**

```powershell
$env:THUNDER_DATABASE_URL='sqlite:///tmp/qa_migration.db'
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
```

Expected: all migrations apply and Alembic reports `No new upgrade operations detected.`

**Stop condition:** any automated failure blocks browser and device testing.

---

## Task 3: Verify Backend Startup And API Contracts

**Files:**
- Read: `server/main.py`
- Read: `server/api/jobs.py`
- Read: `server/api/devices.py`
- Read: `server/api/leads.py`

- [ ] **Step 1: Start the service**

```powershell
.\start_system.bat
```

Expected: one server process listens on `127.0.0.1:8000`.

- [ ] **Step 2: Verify health and OpenAPI**

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/openapi.json
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/
```

Expected: both return HTTP `200`; root HTML includes `/static/js/api.js`, `/static/js/jobs.js`, `/static/js/devices.js`.

- [ ] **Step 3: Register or log in the QA user**

```powershell
$body = @{
  username = $env:THUNDER_QA_USERNAME
  password = $env:THUNDER_QA_PASSWORD
} | ConvertTo-Json
$auth = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/auth/login `
  -ContentType 'application/json' -Body $body
$headers = @{ Authorization = "Bearer $($auth.access_token)" }
```

Expected: token is non-empty. If the user does not exist, register it through `/api/auth/register` and retry login.

- [ ] **Step 4: Query core operational endpoints**

```powershell
$state = Invoke-RestMethod -Headers $headers http://127.0.0.1:8000/api/dashboard/state
$jobs = Invoke-RestMethod -Headers $headers 'http://127.0.0.1:8000/api/jobs?limit=20'
$devices = Invoke-RestMethod -Headers $headers http://127.0.0.1:8000/api/devices
$leads = Invoke-RestMethod -Headers $headers 'http://127.0.0.1:8000/api/leads?limit=20'
$state | ConvertTo-Json -Depth 8 | Set-Content "$qaDir\dashboard-state.json" -Encoding utf8
$jobs | ConvertTo-Json -Depth 8 | Set-Content "$qaDir\jobs.json" -Encoding utf8
$devices | ConvertTo-Json -Depth 8 | Set-Content "$qaDir\devices.json" -Encoding utf8
```

Expected:

- Dashboard contains `project`, `lead_inventory`, `device_matrix`, `active_jobs`.
- Jobs is an array.
- Devices is an array.
- Leads contains `leads`, `total`, `limit`, `offset`.

- [ ] **Step 5: Verify tenant isolation**

Create a second QA user and verify it cannot read the first user's industry, job, device or lead IDs.

Expected: HTTP `404` or empty owned collection, never another tenant's object.

---

## Task 4: Browser UI And Responsive Workflow

**Files:**
- Test: `server/static/index.html`
- Test: `server/static/js/api.js`
- Test: `server/static/js/jobs.js`
- Test: `server/static/js/devices.js`

The browser flow under test is: login page → authenticate → control center → project/lead/job/device views → cancel action → expected visible state.

- [ ] **Step 1: Open the UI at desktop size**

Viewport: `1440x900`. Navigate to `http://127.0.0.1:8000/`.

Expected:

- Login screen is not blank.
- No framework or JavaScript error overlay.
- Username, password and login controls are visible.
- No horizontal page overflow.

- [ ] **Step 2: Capture console baseline**

Record browser `error` and `warn` logs in `browser-console.txt`.

Expected: no `ReferenceError`, failed JavaScript module load, unhandled promise rejection or repeated 429 response.

- [ ] **Step 3: Log in using the QA account**

Actions:

1. Fill username.
2. Fill password.
3. Click `立即登录`.
4. Wait for `控制中心`.

Expected: token stored, dashboard visible, no redirect loop.

- [ ] **Step 4: Verify every primary view**

Open in sequence:

1. 控制中心
2. 获客项目配置
3. 设备准备与检测
4. 线索池管理
5. 执行记录
6. 系统设置
7. 效果分析

Expected: each view renders a meaningful empty/data state; no stale loading indicator; controls do not overlap.

- [ ] **Step 5: Verify the long project modal**

Open new/edit project modal at `1440x900` and `1366x768`.

Expected:

- Modal content scrolls internally.
- Save and Cancel remain reachable.
- No field or button is clipped below the viewport.
- Escape/Cancel closes without saving.

- [ ] **Step 6: Verify task cancellation UI**

With a seeded running fake/test job:

1. Open 执行记录.
2. Click 取消.
3. Confirm.
4. Observe `cancelling` then `cancelled`.

Expected: UI calls `POST /api/jobs/{job_id}/cancel`; the job never returns to `done`.

- [ ] **Step 7: Verify mobile viewport**

Viewport: `390x844`.

Expected:

- Login controls fit.
- Main navigation remains usable.
- Modal Save/Cancel buttons are reachable.
- Tables either scroll horizontally inside their container or switch to a compact layout.
- Text does not overlap buttons.

- [ ] **Step 8: Save screenshots**

Required screenshots:

- Desktop login
- Desktop control center
- Project modal bottom actions
- Job cancelling/cancelled
- Mobile control center
- Mobile project modal

**Stop condition:** any JavaScript exception, invisible action button, scroll trap or stale task state blocks real-device testing.

---

## Task 5: Collection, Funnel And Deduplication

**Files:**
- Test: `core/discover.py`
- Test: `core/classify.py`
- Test: `server/services/task_stats.py`
- Test: `server/models/task.py`

- [ ] **Step 1: Create the QA industry**

Configure:

- One platform only: Douyin.
- One target competitor account.
- 3-5 search keywords.
- Intent keywords and noise keywords.
- Sending disabled during collection verification.

Expected: reopening the project and restarting the service retains target accounts and keywords.

- [ ] **Step 2: Run target-account collection**

Start one collection job and record its `job_id`.

Expected:

- Job progresses `running → done`.
- Target account is retained in project data.
- `collect_summary.candidate_comments`, `classified_passed`, `enqueued` are present.

- [ ] **Step 3: Verify keyword discovery also runs**

Inspect collected leads and source attribution.

Expected: results include target-account sources and keyword sources when both produce candidates. The collector must not limit the run to target accounts only.

- [ ] **Step 4: Verify intent funnel manually**

Sample at least 30 comments:

| Classification | Manual requirement |
|---|---|
| High intent | Explicit need, consultation, price, qualification or action intent |
| Medium intent | Relevant but weak or exploratory intent |
| Noise | Irrelevant, advertisement, emoji-only, duplicate or non-target topic |

Calculate precision:

```text
precision = correctly accepted leads / all accepted leads
```

Acceptance: precision at least `85%`; noise accepted as intent below `10%`.

- [ ] **Step 5: Run the same collection again**

Expected:

- Existing `(comment_id, video_id)` rows are not duplicated.
- Existing target accounts are not duplicated.
- New keyword candidates may enter the lead pool.
- `enqueued` may be lower than `classified_passed` because deduplication is active.

- [ ] **Step 6: Verify platform exclusivity**

Attempt to select multiple collection platforms.

Expected: UI and backend persist exactly one platform for one collection job.

---

## Task 6: Single Real Device Dry-Run

**Files:**
- Test: `core/device/adb_client.py`
- Test: `core/adb_keyboard.py`
- Test: `core/agent/perception.py`
- Test: `core/vision/ui_parser.py`
- Test: `core/task/send_verifier.py`

- [ ] **Step 1: Verify ADB connectivity**

```powershell
adb devices -l
```

Expected: exactly the selected QA device is `device`, not `offline` or `unauthorized`.

- [ ] **Step 2: Scan and bind the device**

Use the Web UI `一键扫描设备`.

Expected:

- Device appears once.
- ADB serial matches.
- Runtime status is `idle`.
- Health score is present.

- [ ] **Step 3: Verify automatic ADB Keyboard preparation**

Remove/disable ADB Keyboard on the test phone, then run Prepare Keyboard.

Expected:

- Missing keyboard is installed from `data/ADBKeyboard.apk` when authorization allows.
- Keyboard is enabled and selected.
- Backend records `keyboard_ready=true`.
- Failure produces `keyboard_error`, not a fake idle state.

- [ ] **Step 4: Run perception without sending**

Capture:

- Current package/activity
- Screenshot
- OCR text/provider/status
- UI XML element count
- Inferred screen and confidence
- Blocker

Expected: screen is not blank; login/captcha/risk-control states are recognized as blockers.

- [ ] **Step 5: Navigate to the exact QA target profile in dry-run**

Expected: observed account identifier exactly matches the configured test target. Any ambiguity fails the test.

- [ ] **Step 6: Stop before final send**

Expected: no message is sent; task remains pending/released; screenshot and execution evidence are retained.

---

## Task 7: Single Real Device Controlled Send

**Files:**
- Test: `core/task/runner.py`
- Test: `core/task/worker.py`
- Test: `core/task/scheduler.py`
- Test: `server/workers.py`

- [ ] **Step 1: Seed exactly one pending QA lead**

Expected: lead status is `pending`; no other pending lead exists for the QA industry.

- [ ] **Step 2: Start sending with one selected device**

Record `job_id`, `device_id`, `task_id` and `claim_token`.

Expected: task becomes `claimed`, device becomes `running`, and daily quota `reserved` increases by exactly one.

- [ ] **Step 3: Observe the physical phone**

Expected sequence:

1. Douyin opens.
2. Correct account is searched.
3. Correct profile is confirmed.
4. Private-message screen opens.
5. Message text is entered.
6. Send is tapped once.

- [ ] **Step 4: Verify delivery evidence**

Expected: one of these must be true:

- `message_sent` screen with confidence at least `0.5`.
- Chat screen contains the complete normalized message in OCR/UI text.

If neither is true, result must be `unconfirmed_send`; the task must not become `done`.

- [ ] **Step 5: Verify database and UI state**

Expected:

- Task is `done` only after evidence confirmation.
- `processed_at` is the successful send time.
- ExecutionLog contains verification reason/confidence.
- ScreenSnapshot contains post-send screenshot/OCR/UI tree.
- Device returns to `idle` only if not isolated, offline, keyboard_error or cooldown.
- Quota changes from `reserved=1` to `sent+1, reserved-1`.

- [ ] **Step 6: Verify the message on the receiver account**

Expected: exactly one message exists on the intended QA receiver account; no message was sent to another account.

---

## Task 8: Cancellation And Failure Recovery

**Files:**
- Test: `core/task/job_state.py`
- Test: `server/workers.py`
- Test: `core/device/supervisor.py`

- [ ] **Step 1: Cancel before a task is claimed**

Expected: job becomes `cancelled`, zero tasks claimed, zero phone actions.

- [ ] **Step 2: Cancel after claim but before send**

Expected within 20 seconds:

- Phone action stops at a safe point.
- Claimed task returns to `pending`.
- Quota reservation is released.
- Job becomes `cancelled`.

- [ ] **Step 3: Cancel during PhoneAgent execution**

Expected: stop event is observed; foreground app is stopped if needed; late worker completion cannot overwrite `cancelled` with `done`.

- [ ] **Step 4: Disconnect USB during execution**

Expected:

- Device becomes `offline`.
- Task is retryable or failed with explicit reason.
- Device is not automatically reset to `idle` by worker cleanup.
- Other devices continue.

- [ ] **Step 5: Trigger keyboard failure**

Expected: device becomes `keyboard_error`; no send is counted; other devices continue.

- [ ] **Step 6: Trigger login/captcha/risk-control screen**

Expected: blocker is persisted; device enters isolated/cooldown policy; no blind retry loop occurs.

- [ ] **Step 7: Restart the backend with a running test job**

Expected: orphan reconciliation marks stale work failed/cancelled according to state, releases claims and does not report a false successful completion.

---

## Task 9: Virtual 30-Device Matrix Load

**Files:**
- Test: `tests/core/task/test_matrix_30_devices.py`
- Run: `scripts/load/matrix_30_devices.py`

- [ ] **Step 1: Run scheduler concurrency tests**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\core\task\test_scheduler.py `
  tests\core\task\test_matrix_30_devices.py -v `
  -p no:cacheprovider --basetemp "$tempRoot\matrix"
```

Expected: all pass.

- [ ] **Step 2: Run 3000-task load**

```powershell
.\.venv\Scripts\python.exe scripts\load\matrix_30_devices.py `
  --devices 30 --tasks 3000 --db-path tmp\matrix_qa.db `
  2>&1 | Tee-Object "$qaDir\matrix-load.json"
```

Acceptance:

```json
{
  "devices": 30,
  "tasks": 3000,
  "claimed": 3000,
  "duplicate_claims": 0,
  "failures": 0,
  "fairness_spread": 0
}
```

- [ ] **Step 3: Test combined limits**

Configure global limit `20` and industry limit `15`.

Expected: at most 15 reservations/sends; one claim consumes one reservation, never two.

- [ ] **Step 4: Cancel a 30-worker simulated job**

Expected: claimed tasks for that job return to pending within 5 seconds; claims belonging to another job are untouched.

---

## Task 10: Real Matrix Staged Rollout

**Files:**
- Evidence: `logs/qa/<run-id>/acceptance.json`
- Read: `server/api/devices.py`
- Read: `core/device/supervisor.py`

Run each stage only after the previous stage passes.

### Stage A: 1 Device

- [ ] Send one message to the dedicated QA receiver.
- [ ] Cancel a second run before final send.
- [ ] Verify task, quota, evidence and UI state.

Acceptance: 1/1 verified send, cancellation succeeds, zero wrong-target actions.

### Stage B: 5 Devices

- [ ] Connect five devices and scan.
- [ ] Confirm all keyboards and health states.
- [ ] Seed five dedicated QA targets or one approved receiver per device.
- [ ] Start one send job.

Acceptance: no duplicate task claims, no device receives another device's task, all failures have explicit reasons, cancellation stops all five.

### Stage C: 10 Devices

- [ ] Repeat with ten devices and ten tasks.
- [ ] Disconnect one device during execution.
- [ ] Put one device in keyboard_error.

Acceptance: eight healthy devices continue; failed devices are isolated correctly; no global job hang.

### Stage D: 30 Devices

- [ ] Connect and scan all 30 devices.
- [ ] Confirm serial-to-name mapping.
- [ ] Verify global quota and per-device daily limit.
- [ ] Seed exactly 30 approved QA tasks.
- [ ] Start one matrix job and monitor `/api/jobs/{job_id}/devices`.
- [ ] Cancel a second 30-device run.

Acceptance:

- 30 unique task claims.
- Zero wrong-target sends.
- Zero duplicate sends.
- Every `done` task has send evidence.
- Cancelled run reaches terminal state within 20 seconds after workers stop.
- Offline/isolated/cooldown devices are not rescheduled.
- UI remains responsive and polling produces no 429 storm.

---

## Task 11: Final Regression And Release Decision

**Files:**
- Output: `logs/qa/<run-id>/acceptance.json`
- Update: `docs/superpowers/audits/2026-06-21-release-test-report.md`

- [ ] **Step 1: Run the full automated suite again**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short `
  -p no:cacheprovider --basetemp "$tempRoot\final"
.\.venv\Scripts\python.exe -m ruff check core server adapters tests cli.py
.\.venv\Scripts\python.exe -m mypy core server adapters cli.py --ignore-missing-imports
.\.venv\Scripts\alembic.exe check
```

Expected: all commands exit `0`.

- [ ] **Step 2: Check runtime logs**

Search for:

```powershell
rg -n "Traceback|ERROR|unconfirmed_send|cancelled_timeout|database is locked|429|duplicate|quota" logs server.log server.err.log
```

Expected: every error is linked to a test case and explained; no unexplained traceback, DB lock storm or duplicate claim.

- [ ] **Step 3: Produce acceptance JSON**

Required fields:

```json
{
  "automated_tests": "pass",
  "api_contract": "pass",
  "browser_desktop": "pass",
  "browser_mobile": "pass",
  "collection_precision": 0.0,
  "deduplication": "pass",
  "single_device_send": "pass",
  "cancellation": "pass",
  "virtual_30_devices": "pass",
  "real_30_devices": "pass_or_not_run",
  "release_decision": "go_or_no_go"
}
```

- [ ] **Step 4: Apply the release gate**

Release is `GO` only when:

1. Automated tests, ruff, mypy and migrations pass.
2. API contract routes and response schemas pass.
3. Browser desktop/mobile checks pass without relevant console errors.
4. Collection precision is at least 85%.
5. Duplicate collection and duplicate task claims are zero.
6. No task becomes done without screenshot/OCR/UI evidence.
7. Cancellation cannot later become done.
8. Virtual 30-device test has zero failures.
9. The highest real-device stage actually run meets all acceptance criteria.

If real 30-device hardware is unavailable, the release decision must explicitly say `NO-GO FOR 30-DEVICE PRODUCTION`; single-device or virtual success cannot be presented as real matrix proof.

---

## Test Execution Order

| Order | Test layer | Estimated duration | Blocks next layer |
|---:|---|---:|---|
| 1 | Environment and backup | 10 min | Yes |
| 2 | Automated baseline | 10-20 min | Yes |
| 3 | API startup/contracts | 10 min | Yes |
| 4 | Browser desktop/mobile | 30-45 min | Yes |
| 5 | Collection/funnel/dedup | 30-90 min | Yes |
| 6 | Single-device dry-run | 20-40 min | Yes |
| 7 | Single-device live send | 15-30 min | Yes |
| 8 | Cancellation/failure | 30-60 min | Yes |
| 9 | Virtual 30-device load | 5-10 min | Yes |
| 10 | Real 1→5→10→30 rollout | 2-6 hours | Yes |
| 11 | Final regression/report | 20-40 min | Release gate |

## Self-Review

### Coverage

- Backend and database: Tasks 2-3.
- Web UI and responsive behavior: Task 4.
- Collection precision, target persistence and deduplication: Task 5.
- ADB keyboard, OCR and UI parsing: Task 6.
- Real send confirmation: Task 7.
- Cancellation and failure recovery: Task 8.
- 30-device concurrency: Tasks 9-10.
- Release decision: Task 11.

### Placeholder Scan

- No unresolved implementation placeholders are present.
- Every stage has commands or explicit manual actions, expected results, evidence and stop conditions.

