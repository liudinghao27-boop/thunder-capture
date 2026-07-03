# Target Account Collection Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stable backend contract for target-account collection so keyword and target-account sources can run in one collection job with clear attribution, deduplication, and summary metrics.

**Architecture:** Keep `core.discover.run_discovery()` as the orchestration boundary. Add `adapters.mediacrawler.runner.run_target_accounts()` as a platform-adapter contract with an unsupported no-op fallback, then normalize and deduplicate mixed source results in discovery before classification and queue insertion. Extend worker `collect_summary` from the returned comments without changing database schema.

**Tech Stack:** Python 3.14, pytest, FastAPI worker code, MediaCrawler adapter, existing SQLAlchemy models.

---

## File Structure

- `adapters/mediacrawler/runner.py`
  - Owns MediaCrawler subprocess adapter functions.
  - Add `run_target_accounts()` with a stable signature and no-op fallback.

- `core/discover.py`
  - Owns collection orchestration across platforms.
  - Add normalization and deduplication helpers.
  - Call keyword adapter and target-account adapter independently.

- `server/workers.py`
  - Owns job lifecycle and `collect_summary`.
  - Extend summary with keyword/target source counts.

- `tests/adapters/test_mediacrawler.py`
  - Contract tests for adapter function availability and fallback behavior.

- `tests/core/test_discover.py`
  - Orchestration tests for mixed keyword/target collection, deduplication, attribution, and cancellation.

- `tests/server/test_workers.py`
  - Summary contract test for mixed source comments.

---

### Task 1: Adapter Contract For Target Accounts

**Files:**
- Modify: `adapters/mediacrawler/runner.py`
- Test: `tests/adapters/test_mediacrawler.py`

- [ ] **Step 1: Write the failing adapter contract test**

Append this test to `tests/adapters/test_mediacrawler.py`:

```python
@pytest.mark.asyncio
async def test_run_target_accounts_unsupported_fallback_returns_empty(tmp_path, caplog):
    from adapters.mediacrawler.runner import run_target_accounts

    caplog.set_level("INFO")
    result = await run_target_accounts(
        "douyin",
        ["target-a", " target-b ", "target-a"],
        keywords=["征兵"],
        max_videos=3,
        workspace=tmp_path,
    )

    assert result == []
    assert "target account collection unsupported" in caplog.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/adapters/test_mediacrawler.py::test_run_target_accounts_unsupported_fallback_returns_empty -q
```

Expected: FAIL with `ImportError` or missing `run_target_accounts`.

- [ ] **Step 3: Add the minimal adapter function**

Add this function near `run_platform()` in `adapters/mediacrawler/runner.py`:

```python
async def run_target_accounts(
    platform: str,
    target_users: list[str],
    *,
    keywords: list[str] | None = None,
    max_videos: int | None = None,
    workspace: Path | None = None,
) -> list[dict]:
    """Collect comments from configured target accounts.

    This is a stable adapter boundary. Platform-specific account crawling can
    replace this fallback later without changing discovery, classification, or
    queue insertion.
    """
    cleaned_targets = []
    seen = set()
    for target in target_users or []:
        value = str(target).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned_targets.append(value)

    if not cleaned_targets:
        return []

    log.info(
        "target account collection unsupported: platform=%s targets=%s workspace=%s",
        platform,
        len(cleaned_targets),
        workspace or MC_DIR,
    )
    return []
```

- [ ] **Step 4: Run the adapter test to verify it passes**

Run:

```powershell
python -m pytest tests/adapters/test_mediacrawler.py::test_run_target_accounts_unsupported_fallback_returns_empty -q
```

Expected: PASS.

---

### Task 2: Discovery Orchestration For Mixed Sources

**Files:**
- Modify: `core/discover.py`
- Test: `tests/core/test_discover.py`

- [ ] **Step 1: Write the failing mixed-source orchestration test**

Append this test to `tests/core/test_discover.py`:

```python
@pytest.mark.asyncio
async def test_run_discovery_collects_keyword_and_target_account_sources(monkeypatch, tmp_path):
    import core.discover as discover

    calls = {"keyword": [], "target": []}

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(platform, keywords, *, max_authors=12, workspace=None, target_users=None):
        calls["keyword"].append((platform, list(keywords), list(target_users or [])))
        return [{
            "text": "关键词评论",
            "source_sec_uid": "sec-keyword",
            "source_short_id": "comment-keyword",
            "source_video_id": "video-keyword",
            "source_keyword": ",".join(keywords),
        }]

    async def fake_run_target_accounts(platform, target_users, *, keywords=None, max_videos=None, workspace=None):
        calls["target"].append((platform, list(target_users), list(keywords or [])))
        return [{
            "text": "对标评论",
            "source_sec_uid": "sec-target",
            "source_short_id": "comment-target",
            "source_video_id": "video-target",
            "source_creator": "target-a",
        }]

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(discover, "configure_mediacrawler", lambda *args, **kwargs: None)
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["征兵"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry)

    assert calls["keyword"] == [("douyin", ["征兵"], ["target-a"])]
    assert calls["target"] == [("douyin", ["target-a"], ["征兵"])]
    assert [c["source_type"] for c in comments] == ["keyword", "target_account"]
    assert comments[0]["source_keyword"] == "征兵"
    assert comments[1]["source_keyword"] == "target:target-a"
    assert comments[1]["source_creator"] == "target-a"
    assert {c["industry_slug"] for c in comments} == {"test-ind"}
```

- [ ] **Step 2: Run the mixed-source test to verify it fails**

Run:

```powershell
python -m pytest tests/core/test_discover.py::test_run_discovery_collects_keyword_and_target_account_sources -q
```

Expected: FAIL because `core.discover` does not import/call `run_target_accounts` and does not assign `source_type`.

- [ ] **Step 3: Implement discovery normalization helpers**

In `core/discover.py`, update imports:

```python
from adapters.mediacrawler.runner import (
    configure_mediacrawler,
    prepare_mediacrawler_workspace,
    run_platform,
    run_target_accounts,
)
```

Add helpers after `_unique_clean()`:

```python
def _dedupe_key(comment: dict) -> tuple[str, str, str] | tuple[str, str, str, str]:
    platform = str(comment.get("source_platform", "")).strip()
    video_id = str(comment.get("source_video_id", "")).strip()
    comment_id = str(comment.get("source_short_id", "")).strip()
    if video_id and comment_id:
        return ("stable", platform, video_id, comment_id)
    return (
        "fallback",
        platform,
        str(comment.get("source_sec_uid", "")).strip(),
        str(comment.get("text", "")).strip(),
    )


def _normalize_comment(
    comment: dict,
    *,
    industry_slug: str,
    platform: str,
    source_type: str,
    source_keyword: str,
    source_creator: str = "",
) -> dict:
    normalized = dict(comment)
    normalized["industry_slug"] = industry_slug
    normalized.setdefault("source_platform", platform)
    normalized["source_type"] = source_type
    if source_keyword:
        normalized["source_keyword"] = source_keyword
    if source_creator:
        normalized["source_creator"] = source_creator
    return normalized
```

- [ ] **Step 4: Implement mixed-source orchestration**

Replace the current per-platform collection body in `run_discovery()` with:

```python
            keyword_comments = await run_platform(
                p,
                keywords if isinstance(keywords, list) else [str(keywords)],
                workspace=workspace,
                target_users=target_users,
            )

            normalized_comments = [
                _normalize_comment(
                    c,
                    industry_slug=industry.slug,
                    platform=p,
                    source_type="keyword",
                    source_keyword=str(c.get("source_keyword") or ",".join(keywords)),
                )
                for c in keyword_comments
            ]

            if should_stop and should_stop():
                log.info("Discovery cancelled after keyword collection for %s", p)
                break

            target_comments = await run_target_accounts(
                p,
                target_users,
                keywords=keywords,
                max_videos=getattr(industry, "collect_video_limit", None),
                workspace=workspace,
            )
            for c in target_comments:
                creator = str(c.get("source_creator") or c.get("source_sec_uid") or "").strip()
                normalized_comments.append(
                    _normalize_comment(
                        c,
                        industry_slug=industry.slug,
                        platform=p,
                        source_type="target_account",
                        source_keyword=f"target:{creator}" if creator else str(c.get("source_keyword", "")),
                        source_creator=creator,
                    )
                )

            seen: dict[tuple, int] = {}
            for c in normalized_comments:
                key = _dedupe_key(c)
                existing_index = seen.get(key)
                if existing_index is None:
                    seen[key] = len(all_comments)
                    all_comments.append(c)
                    continue
                if c.get("source_type") == "target_account":
                    all_comments[existing_index] = c
```

- [ ] **Step 5: Run the mixed-source test to verify it passes**

Run:

```powershell
python -m pytest tests/core/test_discover.py::test_run_discovery_collects_keyword_and_target_account_sources -q
```

Expected: PASS.

---

### Task 3: Deduplication Prefers Target Attribution

**Files:**
- Modify: `core/discover.py` if Task 2 is incomplete
- Test: `tests/core/test_discover.py`

- [ ] **Step 1: Write the failing deduplication test**

Append:

```python
@pytest.mark.asyncio
async def test_run_discovery_dedupes_same_comment_and_prefers_target_source(monkeypatch, tmp_path):
    import core.discover as discover

    class FakeBrowser:
        port = 9222
        def __init__(self, user_data_dir): self.user_data_dir = user_data_dir
        def start(self): return None
        def close(self): return None

    duplicate = {
        "text": "同一条评论",
        "source_sec_uid": "sec-1",
        "source_short_id": "comment-1",
        "source_video_id": "video-1",
    }

    async def fake_run_platform(*args, **kwargs):
        return [dict(duplicate, source_keyword="征兵")]

    async def fake_run_target_accounts(*args, **kwargs):
        return [dict(duplicate, source_creator="target-a")]

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(discover, "configure_mediacrawler", lambda *args, **kwargs: None)
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["征兵"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry)

    assert len(comments) == 1
    assert comments[0]["source_type"] == "target_account"
    assert comments[0]["source_keyword"] == "target:target-a"
    assert comments[0]["source_creator"] == "target-a"
```

- [ ] **Step 2: Run the deduplication test**

Run:

```powershell
python -m pytest tests/core/test_discover.py::test_run_discovery_dedupes_same_comment_and_prefers_target_source -q
```

Expected: PASS after Task 2 implementation. If it fails, fix `_dedupe_key()` or target preference logic only.

---

### Task 4: Cancellation Between Source Phases

**Files:**
- Modify: `core/discover.py`
- Test: `tests/core/test_discover.py`

- [ ] **Step 1: Write the failing cancellation test**

Append:

```python
@pytest.mark.asyncio
async def test_run_discovery_stops_before_target_collection_when_cancelled(monkeypatch, tmp_path):
    import core.discover as discover

    calls = {"target": 0}
    stop_checks = {"count": 0}

    class FakeBrowser:
        port = 9222
        def __init__(self, user_data_dir): self.user_data_dir = user_data_dir
        def start(self): return None
        def close(self): return None

    async def fake_run_platform(*args, **kwargs):
        return [{
            "text": "关键词评论",
            "source_sec_uid": "sec-keyword",
            "source_short_id": "comment-keyword",
            "source_video_id": "video-keyword",
            "source_keyword": "征兵",
        }]

    async def fake_run_target_accounts(*args, **kwargs):
        calls["target"] += 1
        return []

    def should_stop():
        stop_checks["count"] += 1
        return stop_checks["count"] >= 2

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(discover, "configure_mediacrawler", lambda *args, **kwargs: None)
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["征兵"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry, should_stop=should_stop)

    assert calls["target"] == 0
    assert len(comments) == 1
    assert comments[0]["source_type"] == "keyword"
```

- [ ] **Step 2: Run the cancellation test**

Run:

```powershell
python -m pytest tests/core/test_discover.py::test_run_discovery_stops_before_target_collection_when_cancelled -q
```

Expected: PASS after Task 2 implementation. If it fails, place the `should_stop()` check after keyword normalization and before `run_target_accounts()`.

---

### Task 5: Worker Collection Summary Source Breakdown

**Files:**
- Modify: `server/workers.py`
- Test: `tests/server/test_workers.py`

- [ ] **Step 1: Write the failing summary test**

Append or update a worker test so `run_collect_job()` receives mixed source comments:

```python
def test_run_collect_job_persists_source_breakdown_summary(db_session):
    cfg = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["kw"],
        reply_tone="",
        reply_style="",
        categories=["咨询"],
        platforms=["douyin"],
        target_users=["target-a"],
        user_id="u1",
    )
    comments = [
        {
            "industry_slug": "test-ind",
            "text": "关键词评论",
            "source_sec_uid": "sec-keyword",
            "source_short_id": "comment-keyword",
            "source_video_id": "video-keyword",
            "source_type": "keyword",
        },
        {
            "industry_slug": "test-ind",
            "text": "对标评论",
            "source_sec_uid": "sec-target",
            "source_short_id": "comment-target",
            "source_video_id": "video-target",
            "source_type": "target_account",
        },
    ]

    async def fake_run_discovery(*args, **kwargs):
        return comments

    with patch("server.workers.run_discovery", fake_run_discovery), \
         patch("server.workers.classify_batch", return_value=comments), \
         patch("server.workers.enqueue_classified_result", return_value={
             "received": 2,
             "valid": 2,
             "inserted": 2,
             "duplicates": 0,
             "invalid": 0,
         }), \
         patch("server.workers.get_llm_client", return_value=object()):
        job_id = run_collect_job(cfg)
        time.sleep(0.2)

    status = get_job_status(job_id, user_id="u1")
    summary = status["collect_summary"]
    assert summary["candidate_comments"] == 2
    assert summary["keyword_candidates"] == 1
    assert summary["target_candidates"] == 1
    assert summary["deduped_candidates"] == 2
    assert summary["source_breakdown"] == {"keyword": 1, "target_account": 1}
```

- [ ] **Step 2: Run the summary test to verify it fails**

Run:

```powershell
python -m pytest tests/server/test_workers.py::test_run_collect_job_persists_source_breakdown_summary -q
```

Expected: FAIL because the new summary fields are missing.

- [ ] **Step 3: Add summary helper in `server/workers.py`**

Add near `run_collect_job()`:

```python
def _collect_source_breakdown(comments: list[dict] | None) -> dict:
    breakdown = {"keyword": 0, "target_account": 0}
    for comment in comments or []:
        source_type = str(comment.get("source_type") or "keyword").strip()
        if source_type not in breakdown:
            breakdown[source_type] = 0
        breakdown[source_type] += 1
    return breakdown
```

- [ ] **Step 4: Extend `collect_summary`**

In `run_collect_job()`, before `collect_summary = {...}`:

```python
            source_breakdown = _collect_source_breakdown(comments)
```

Inside `collect_summary`, add:

```python
                "keyword_candidates": int(source_breakdown.get("keyword", 0)),
                "target_candidates": int(source_breakdown.get("target_account", 0)),
                "deduped_candidates": len(comments or []),
                "source_breakdown": source_breakdown,
```

- [ ] **Step 5: Run the summary test to verify it passes**

Run:

```powershell
python -m pytest tests/server/test_workers.py::test_run_collect_job_persists_source_breakdown_summary -q
```

Expected: PASS.

---

### Task 6: Regression Verification

**Files:**
- No source edits unless failures identify a defect.

- [ ] **Step 1: Run focused discovery and adapter tests**

Run:

```powershell
python -m pytest tests/adapters/test_mediacrawler.py tests/core/test_discover.py tests/server/test_workers.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run SOP contract subset**

Run:

```powershell
python -m pytest tests/server/api/test_frontend_contract.py tests/server/api/test_static_modules.py tests/server/api/test_execution_views.py tests/server/api/test_leads_tenant.py tests/core/task/test_matrix_30_devices.py tests/core/task/test_send_verifier.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run compile check**

Run:

```powershell
python -m compileall core server adapters -q
```

Expected: exit code 0.

- [ ] **Step 4: Clean generated test artifacts**

Run:

```powershell
Remove-Item -Recurse -Force .pytest_cache -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Where-Object { $_.FullName -notlike '*\.venv\*' } | Remove-Item -Recurse -Force
Remove-Item data\test_thunder.db,data\test_thunder.db-shm,data\test_thunder.db-wal -Force -ErrorAction SilentlyContinue
```

Expected: generated caches and test DB are removed.

---

## Self-Review

- Spec coverage:
  - Adapter boundary: Task 1.
  - Mixed keyword and target collection: Task 2.
  - Source attribution: Task 2.
  - Deduplication and target preference: Task 3.
  - Cancellation: Task 4.
  - Summary metrics: Task 5.
  - Regression verification: Task 6.

- Placeholder scan:
  - No unfinished markers or vague implementation steps are intentionally left in this plan.

- Type consistency:
  - Adapter name is consistently `run_target_accounts`.
  - Source type values are consistently `keyword` and `target_account`.
  - Summary fields are consistently `keyword_candidates`, `target_candidates`, `deduped_candidates`, and `source_breakdown`.
