# Target Account Collection Contract Design

## Goal

Build the backend contract for target-account collection without tying the core workflow to one platform implementation. A collection run must support both keyword search and target-account sources in the same job, keep their source attribution separate, deduplicate safely, and expose enough funnel metrics to explain why leads did or did not enter the queue.

This phase does not implement platform-specific account crawling internals for Douyin, Kuaishou, Xiaohongshu, or Video Accounts. It creates the adapter boundary and data contract so those platform implementations can be added without changing the worker, classifier, queue, or API contract again.

## Scope

In scope:

- Add a target-account collection adapter contract.
- Update `core.discover.run_discovery()` to call keyword collection and target-account collection independently.
- Ensure account-sourced comments carry explicit source fields.
- Preserve keyword collection when target accounts are configured.
- Add collection summary metrics for keyword and target-account candidates.
- Add tests proving source attribution, deduplication, cancellation, and summary behavior.

Out of scope:

- Real platform-specific MediaCrawler account-page implementation.
- Web UI visual changes.
- Real-device send testing.
- Database schema changes unless tests reveal an existing field cannot support attribution.

## Architecture

### Existing Boundary

Current flow:

```text
run_collect_job()
  -> run_discovery()
      -> adapters.mediacrawler.runner.run_platform(platform, keywords, target_users)
  -> classify_batch()
  -> enqueue_classified_result()
  -> collect_summary
```

Problem:

`target_users` is passed into `run_platform()`, but `run_platform()` still executes only keyword search. The system can report target-account configuration counts, but it cannot prove that target-account sources were collected separately.

### Proposed Boundary

Add a separate adapter function:

```python
async def run_target_accounts(
    platform: str,
    target_users: list[str],
    *,
    keywords: list[str] | None = None,
    max_videos: int | None = None,
    workspace: Path | None = None,
) -> list[dict]:
    ...
```

`run_discovery()` becomes the orchestrator:

```text
for platform in configured_platforms:
  keyword_comments = run_platform(platform, keywords)
  target_comments = run_target_accounts(platform, target_users, keywords=keywords)
  normalize both source types
  deduplicate within the run
  return combined comments
```

The first implementation of `run_target_accounts()` may be a no-op fallback returning an empty list when the underlying platform does not yet support account crawling. The critical part is that the boundary, source attribution, and summary metrics are stable.

## Data Contract

Every returned comment must remain compatible with classification and queue insertion:

```python
{
    "text": "...",
    "source_name": "...",
    "source_sec_uid": "...",
    "source_short_id": "...",
    "source_video_id": "...",
    "source_keyword": "...",
    "source_platform": "douyin",
    "industry_slug": "...",
}
```

For keyword-sourced comments:

```python
"source_keyword": "征兵,军考"
"source_creator": ""
"source_type": "keyword"
```

For target-account-sourced comments:

```python
"source_keyword": "target:<account_id>"
"source_creator": "<account_id>"
"source_type": "target_account"
```

`source_type` is optional for existing consumers but required for new tests and future analytics. Queue insertion already supports `source_creator`, `source_keyword`, and `platform`.

## Deduplication Rules

Within one collection run:

- Prefer stable key: `(source_platform, source_video_id, source_short_id)`.
- Fallback key: `(source_platform, source_sec_uid, text)`.
- If the same comment appears from keyword and target-account collection, keep one row.
- If source types conflict for the same comment, prefer `target_account` attribution because it is more specific.

Database-level queue dedup remains handled by `(comment_id, video_id)`.

## Cancellation

`run_discovery()` must check `should_stop()`:

- Before each platform.
- After keyword collection and before target-account collection.
- Before appending normalized results.

If cancellation is requested, the function returns the comments collected so far. The worker already marks the job cancelled before classification when it sees cancellation after discovery.

## Collection Summary

Extend `collect_summary` with stable fields:

```json
{
  "candidate_comments": 0,
  "classified_passed": 0,
  "enqueued": 0,
  "queue_received": 0,
  "queue_valid": 0,
  "queue_duplicates": 0,
  "queue_invalid": 0,
  "platforms": ["douyin"],
  "target_user_count": 0,
  "keyword_count": 0,
  "keyword_candidates": 0,
  "target_candidates": 0,
  "deduped_candidates": 0,
  "source_breakdown": {
    "keyword": 0,
    "target_account": 0
  }
}
```

`candidate_comments` remains the final deduplicated count passed into classification.

## Tests

Add tests first:

- `tests/core/test_discover.py`
  - `run_discovery()` calls keyword and target-account adapters when both inputs exist.
  - target-account comments are attributed with `source_type="target_account"` and `source_keyword="target:<id>"`.
  - duplicate comments from both sources collapse to one, preferring target-account attribution.
  - cancellation between keyword and target collection prevents target adapter call.

- `tests/adapters/test_mediacrawler.py`
  - adapter exposes `run_target_accounts()` with stable signature.
  - default unsupported implementation returns an empty list and logs a clear message.

- `tests/server/test_workers.py`
  - `collect_summary` includes keyword and target candidate counts when discovery returns mixed sources.

## Risks

- Platform account crawling support is uneven. The contract must allow unsupported platforms to return empty account results without breaking keyword collection.
- Existing analytics may infer source type from `source_keyword`. Keeping `source_keyword="target:<id>"` preserves compatibility.
- `source_type` is a new field in in-memory comment dictionaries. It should not require a database migration unless later analytics need it persisted directly.

## Acceptance Criteria

- Keyword-only collection behavior stays compatible.
- Target-only collection behavior does not crash.
- Mixed keyword and target-account collection produces one deduplicated candidate list.
- Queue insertion still works with the existing schema.
- `collect_summary` can explain candidate source mix and queue dedup.
- Existing SOP contract tests continue to pass.
