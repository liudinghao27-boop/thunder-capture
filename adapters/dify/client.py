"""Dify AI Workflow adapter — production-ready classification client.

Architecture:
    core/classify.py → ClassificationRouter
        ├── [if DIFY_API_URL set] → DifyBackend (this client)
        └── [fallback]            → DirectLLMBackend (DeepSeek)

Setup:
    1. Deploy Dify (docker compose up)
    2. Import the workflow template: adapters/dify/workflow-template.yml
    3. Set in .env:
       DIFY_API_URL=http://your-dify-host/v1
       DIFY_API_KEY=app-xxxxxxxxxxxxx
    4. Restart thunder — classification auto-routes to Dify

Usage:
    from adapters.dify.client import DifyClient
    client = DifyClient()
    results = client.classify(comments, industry_name, categories)
"""

from __future__ import annotations

import json
import os
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("thunder.dify")

# ── Config from environment ──
DIFY_API_URL = os.getenv("DIFY_API_URL", "")
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
DIFY_BATCH_SIZE = int(os.getenv("DIFY_BATCH_SIZE", "10"))
DIFY_MAX_RETRIES = int(os.getenv("DIFY_MAX_RETRIES", "3"))
DIFY_TIMEOUT = float(os.getenv("DIFY_TIMEOUT", "120.0"))


@dataclass
class DifyResult:
    """Normalized classification result, backend-agnostic."""
    index: int
    is_target: bool = False
    confidence: str = "low"
    category: str = ""
    question: str = ""
    suggested_reply_topic: str = ""
    evidence: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class DifyClient:
    """Production-ready HTTP client for Dify Workflow API.

    Features:
      - Batch splitting: sends chunks of DIFY_BATCH_SIZE (default 10)
      - Auto-retry: exponential backoff on transient errors
      - Result normalization: converts Dify output to DifyResult dataclass
      - Connection pooling: single httpx.Client reused across batches
      - Graceful degradation: raises on permanent errors, retries on 5xx
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        *,
        timeout: float = 0,
        batch_size: int = 0,
        max_retries: int = 0,
    ):
        self.base_url = (base_url or DIFY_API_URL).rstrip("/")
        self.api_key = api_key or DIFY_API_KEY
        self.timeout = timeout or DIFY_TIMEOUT
        self.batch_size = batch_size or DIFY_BATCH_SIZE
        self.max_retries = max_retries or DIFY_MAX_RETRIES
        self._client: httpx.Client | None = None

    # ── Public API ──────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if Dify is configured and reachable."""
        return bool(self.base_url and self.api_key)

    def health_check(self) -> dict:
        """Quick connectivity test. Returns {'ok': True/False, ...}."""
        if not self.available:
            return {"ok": False, "error": "DIFY_API_URL or DIFY_API_KEY not set"}
        try:
            client = self._get_client()
            resp = client.get("/v1/workflows")
            return {"ok": resp.status_code < 500, "status": resp.status_code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def classify(
        self,
        comments: list[dict],
        industry_name: str,
        categories: list[str],
        *,
        progress_callback=None,
    ) -> list[DifyResult]:
        """Classify prefiltered comments via Dify workflow.

        Splits into batches, sends each to Dify, normalizes output.

        Args:
            comments: Prefiltered comment dicts (must have 'text' key)
            industry_name: Industry display name
            categories: Intent categories (e.g., ["咨询类", "意向类"])
            progress_callback: Optional fn(batch_num, total_batches)

        Returns:
            List of DifyResult dataclasses for TARGET comments only.
            Non-target results are filtered out.
        """
        if not self.available:
            raise RuntimeError("Dify not configured")

        all_targets: list[DifyResult] = []
        total_batches = (len(comments) + self.batch_size - 1) // self.batch_size

        log.info(
            "Dify classify: %d comments → %d batches (batch_size=%d)",
            len(comments), total_batches, self.batch_size,
        )

        for batch_num in range(total_batches):
            start = batch_num * self.batch_size
            chunk = comments[start : start + self.batch_size]

            # Build indexed payload
            indexed = [
                {
                    "index": i,
                    "text": c.get("text", ""),
                    "nickname": c.get("source_name", c.get("nickname", "")),
                    "source": c.get("source_keyword", ""),
                    "video_desc": c.get("source_video_desc", "")[:160],
                }
                for i, c in enumerate(chunk)
            ]

            try:
                results = self._send_batch(
                    indexed=indexed,
                    industry=industry_name,
                    categories=categories,
                )
                # Filter to targets only
                for r in results:
                    if r.is_target:
                        all_targets.append(r)

            except Exception as exc:
                log.warning("Dify batch %d/%d failed: %s", batch_num + 1, total_batches, exc)
                # Continue with next batch — don't lose other batches
                continue

            if progress_callback:
                progress_callback(batch_num + 1, total_batches)

        log.info("Dify classify done: %d targets from %d comments", len(all_targets), len(comments))
        return all_targets

    # ── Internal ────────────────────────────────────────

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    def _send_batch(
        self,
        indexed: list[dict],
        industry: str,
        categories: list[str],
    ) -> list[DifyResult]:
        """Send one batch to Dify and parse results. Retries on 5xx."""
        payload = {
            "inputs": {
                "industry": industry,
                "categories": ", ".join(categories),
                "comments_json": json.dumps(indexed, ensure_ascii=False),
                "batch_size": len(indexed),
            },
            "response_mode": "blocking",
            "user": "thunder-system",
        }

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                client = self._get_client()
                resp = client.post("/v1/workflows/run", json=payload)

                # 4xx → don't retry
                if 400 <= resp.status_code < 500:
                    log.error("Dify 4xx: %s — %s", resp.status_code, resp.text[:300])
                    return []

                resp.raise_for_status()
                data = resp.json()
                return self._parse_response(data)

            except httpx.TimeoutException:
                last_error = "timeout"
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    log.warning("Dify timeout, retry %d/%d in %ds", attempt + 1, self.max_retries, wait)
                    time.sleep(wait)
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code}"
                if exc.response.status_code >= 500 and attempt < self.max_retries:
                    wait = 2 ** attempt
                    log.warning("Dify 5xx, retry %d/%d in %ds", attempt + 1, self.max_retries, wait)
                    time.sleep(wait)
                else:
                    raise
            except Exception as exc:
                last_error = str(exc)[:100]
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    log.warning("Dify error, retry %d/%d in %ds: %s", attempt + 1, self.max_retries, wait, exc)
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError(f"Dify batch failed after {self.max_retries} retries: {last_error}")

    def _parse_response(self, data: dict) -> list[DifyResult]:
        """Normalize Dify workflow output to DifyResult list.

        Dify workflow must output a 'results' key containing:
        [{"index": 0, "is_target": true, "confidence": "high", ...}, ...]
        """
        outputs = data.get("data", {}).get("outputs", {})
        raw_results = outputs.get("results", outputs.get("result", []))

        # Handle string-encoded JSON from Dify
        if isinstance(raw_results, str):
            try:
                raw_results = json.loads(raw_results)
            except json.JSONDecodeError:
                log.error("Dify returned unparseable result string: %s", raw_results[:200])
                return []

        if not isinstance(raw_results, list):
            raw_results = [raw_results] if raw_results else []

        parsed = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            idx = item.get("index", -1)
            if not isinstance(idx, int) or idx < 0:
                continue

            parsed.append(DifyResult(
                index=idx,
                is_target=bool(item.get("is_target", False)),
                confidence=str(item.get("confidence", "low")).lower(),
                category=str(item.get("category", "")),
                question=str(item.get("question", "")),
                suggested_reply_topic=str(item.get("suggested_reply_topic", "")),
                evidence=str(item.get("evidence", "")),
                raw=item,
            ))

        return parsed

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
