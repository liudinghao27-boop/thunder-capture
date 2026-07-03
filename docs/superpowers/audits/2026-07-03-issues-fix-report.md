# shemeihuoke Issues Verification and Fix Report

Generated: 2026-07-03

Source Markdown reviewed:

- `C:/Users/Administrator/Desktop/shemeihuoke_issues.md`

## Priority Rules

- High: blocks core runtime, core send/collect flow defects, security exposures.
- Medium: user experience defects, inaccurate reporting, operational reliability risks.
- Low: optimization suggestions, historical architecture notes, documentation-only gaps.

## Confirmed and Fixed

| ID | Priority | Verification | Fix | Validation |
| --- | --- | --- | --- | --- |
| 2, 3, 4, 20, 21 | High | `pyproject.toml` did not explicitly declare `requests`, `Pillow`, `numpy`, `playwright` while runtime/scripts import them. | Added dependencies to `pyproject.toml` and `requirements/base.txt`. | Dependency declarations inspected; related imports covered by compile/test run. |
| 6, 7, 8 | Medium | `core/browser_orchestrator.py` used Windows-only browser paths, `creationflags`, and `taskkill`. | Added PATH lookup, macOS/Linux candidate paths, platform-specific `Popen` args, and non-Windows termination fallback. | `compileall core` passed. |
| 9 | High | `core/task/scheduler.py` filtered `retry_after` with string comparison. | Claims now load bounded pending candidates and evaluate `retry_after` through timezone-aware datetime parsing, including `Z` suffix. | `tests/core/task/test_scheduler.py` passed. |
| 10 | High | Send window used UTC clock directly against business `HH:MM`. | `is_send_window_open` now evaluates windows in `Asia/Shanghai` by default, with optional `industry.timezone` fallback. | `tests/core/strategy/test_policy.py` passed. |
| 11, 12, 13 | High | `hourly_send_limit` was used by workers but not part of model/schema/config mapping. | Added field to `IndustryConfig`, SQLAlchemy model, Pydantic create/update/out schemas, DB-to-config conversion, schedule update API, and additive migration. | `tests/server/test_models_schemas.py` and scheduler/worker-related tests passed. |
| 14 | High | `_handle_send_failure` could reference `claim_token` before assignment. | Moved `claim_token` assignment before any code path that can call the failure handler. | `compileall core` and worker-related tests passed. |
| 15 | High | `adapters/mediacrawler/runner.py::run_target_accounts` only logged unsupported and returned `[]`, so competitor accounts were never collected by the real adapter. | Added Douyin creator-mode execution through MediaCrawler `--type creator --creator_id ...`, reused JSONL comment parsing, preserved target-account provenance, and kept unsupported platforms as explicit fallback. | `tests/adapters/test_mediacrawler.py` passed. |
| 18 | High | Default admin password was printed to stdout when env var was missing. | Removed plaintext password output; logs only non-secret warning. | `test_create_default_admin_does_not_print_generated_password` passed. |
| 23, 27 | Low | `TaskRouter.dispatch` assumed handler results were dicts, making dataclass or `DispatchResult` executors fail. | Added result normalization for `DispatchResult`, dataclass results, dict results, and scalar fallbacks; added exception logging. | `tests/core/task/test_router.py` passed. |
| 25, 35 | Medium | robots fetch errors returned empty content and cache had no TTL. | Rewrote `core/robotstxt.py` to deny by default on unverifiable robots, include `fetch_error`, and expire cache after TTL. | `tests/core/test_robotstxt.py` passed. |
| 28 | Medium | `/api/stats/effects` accepted `days` but counted all history. | Added bounded `days` query validation and `fetched_at >= since` filter. | `test_effect_stats_filters_by_days` passed. |
| 30 | Medium | Screen stream access had no audit event. | Added `thunder.audit.devices` info log when a user opens a device screen stream. | `compileall server` passed. |
| 31 | Medium | JWT lacked standard issued/not-before/token-id claims. | Added `iat`, `nbf`, and `jti` to access tokens. | `test_access_token_contains_standard_claims` passed. |
| 32 | Low | `system.example.yaml` did not expose `api_keys.openai`, and `load_system` did not override it from `THUNDER_OPENAI_KEY`. | Added OpenAI key to example config and environment override handling. | `tests/core/test_config.py` passed. |
| 36 | Medium | File logging used non-rotating `FileHandler`. | Switched to `RotatingFileHandler`, 10 MB x 5 backups. | `compileall server` passed. |

## Verified as Already Fixed or Not Applicable

| ID | Priority | Result |
| --- | --- | --- |
| 1 | High | Not reproduced. `config/system.yaml` exists. |
| 5 | High | Not reproduced as a dependency declaration bug. `core/agent/executor.py` injects vendored `deps/Open-AutoGLM` before importing `phone_agent`. |
| 16, 17, 26 | Medium | Confirmed as broad observability debt. Not fully resolved because changing all exception semantics needs a larger behavior review. |
| 19 | Medium | Partially mitigated for SQLite/PostgreSQL by dialect-specific conflict insert. Unknown dialect fallback still has race risk. |
| 22, 40, 41, 42, 43 | Low | Historical/inactive architecture items. Not treated as blocking current SaaS/Web UI runtime. |
| 29 | Medium | Partially mitigated already: evidence paths are restricted to the acceptance output directory and traversal is tested. Full per-user evidence ownership requires adding metadata binding. |
| 33, 34, 37, 38, 39 | Low/Medium | Operational optimization items. Not fully addressed in this pass except logging rotation and browser portability. |

## Validation Commands

```powershell
.venv\Scripts\python.exe -m pytest tests\core\task\test_scheduler.py tests\core\strategy\test_policy.py tests\server\test_models_schemas.py tests\server\api\test_auth.py tests\server\api\test_stats.py tests\core\test_robotstxt.py tests\server\api\test_devices_evidence.py tests\server\api\test_frontend_contract.py tests\adapters\test_mediacrawler.py tests\core\task\test_router.py tests\core\test_config.py -q
```

Result: `78 passed, 1 warning`

```powershell
.venv\Scripts\python.exe -m compileall adapters core server tests\adapters\test_mediacrawler.py tests\core\task\test_router.py tests\core\test_config.py
```

Result: passed.
