# Matrix Stabilization Release Gate

Date: 2026-06-21

## Result

Software release gate: **passed**.

Hardware acceptance gate: **blocked because `adb devices -l` returned no devices**. No real
message was sent during this gate.

## Verified

- API contracts publish structured schemas for dashboard, jobs and leads.
- Job state transitions protect terminal cancellation from late worker completion.
- Send completion requires screenshot/OCR/UI evidence; unconfirmed sends fail closed.
- SQLite matrix claiming is atomic and quota reservation is not double-counted.
- 30 virtual workers claimed 3,000 tasks with zero duplicate claims and even distribution.
- Desktop and 390x844 mobile Web UI flows pass the reusable Playwright acceptance script.
- Project modal keeps cancel/save controls visible on desktop and mobile.
- Mobile navigation uses a full-width content pane and a dismissing drawer.
- Tailwind is served as local compiled CSS; clean browser console has zero errors/warnings.
- Favicon returns 204 and static/API resources return 200/304 as expected.
- Real-device acceptance script defaults to dry-run and requires exact target confirmation plus
  `--max-sends 1` for a live send.

## Release Evidence

- `python -m pytest tests -q -p no:cacheprovider`: 254 passed.
- `ruff check server core tests adapters cli.py scripts/load scripts/smoke/real_device_acceptance.py`: passed.
- `mypy core server adapters`: no issues in 96 source files.
- `alembic upgrade head` and `alembic check`: passed; no new upgrade operations.
- Playwright: seven primary views, desktop/mobile project modal, 390px content width, zero console
  errors and zero warnings.
- Load test: 3,000 tasks, 30 workers, zero duplicate claims, zero failures, fairness spread 0.

## Fixed During Gate

- Added missing `PhoneAgentExecutor.stop()`, preventing worker cleanup from raising after execution.
- Corrected nullable lead timestamps in the `/api/leads` response contract.
- Fixed an unawaited asynchronous collection mock and disposed test database resources in affected
  API suites.
- Corrected SQLAlchemy dialect insert typing while retaining SQLite/PostgreSQL upsert behavior.

## Remaining Gate

Connect one authorized Android QA device and follow
`docs/superpowers/sops/real-device-acceptance.md`:

1. Run dry-run and review health, keyboard, screenshot, OCR, UI tree and target evidence.
2. Run one guarded send only to the dedicated QA receiver.
3. Verify one received message, post-send evidence and database status.
4. Verify cancellation during a second prepared run reaches `cancelled` within 20 seconds.
5. Expand hardware acceptance from 1 to 5, 10 and finally 30 devices.

## Technical Debt

- Several older standalone test fixtures do not dispose their temporary SQLite engines. CI and the
  standard test run are clean, but Python 3.14 with global `-W error` surfaces ResourceWarnings.
- Legacy manual scripts outside the CI lint scope still contain Ruff findings and should be cleaned
  in a separate maintenance pass.
- Tracked `data/chrome_data` runtime files remain dirty; they were not reverted because they may
  contain user session state. New runtime changes are now ignored.
