"""Celery tasks: LLM classification pipeline.

Migration path from core/classify.py classify_batch():
  1. Replace inline DeepSeek API calls with Celery tasks
  2. Optionally route to Dify adapter instead of direct LLM
  3. Each batch is an independent task (parallel classification)
"""

from __future__ import annotations

import logging

from adapters.celery.app import app

log = logging.getLogger("thunder.celery.classify")


@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=120,
)
def classify_batch_task(
    self, comments: list[dict], industry_name: str, categories: list[str]
):
    """Classify a batch of comments via LLM (or Dify if configured).

    This is the Celery-ified version of core/classify.py classify_batch().

    Args:
        comments: Comment dicts with text, nickname, keyword
        industry_name: Industry display name
        categories: Intent categories for classification
    """
    # Try Dify first if configured
    try:
        from adapters.dify.client import DifyClient

        client = DifyClient()
        if client.available:
            log.info("Using Dify for classification (%d comments)", len(comments))
            return client.classify(
                comments=comments,
                industry_name=industry_name,
                categories=categories,
            )
    except Exception as exc:
        log.warning("Dify unavailable, falling back to direct LLM: %s", exc)

    # Fallback: use existing core logic
    from core.classify import classify_batch as _classify_batch
    from core.config import IndustryConfig

    # Build minimal IndustryConfig for classification
    industry = IndustryConfig(
        name=industry_name,
        slug=industry_name.lower().replace(" ", "_"),
        keywords=[],
        categories=categories,
        reply_tone="业内人士",
        reply_style="亲切专业",
        reply_hook="",
    )

    return _classify_batch(comments, industry)


@app.task(bind=True, max_retries=1)
def enqueue_classified_task(self, classified: list[dict]):
    """Enqueue classified comments into the sending queue."""
    from core.classify import enqueue_classified

    count = enqueue_classified(classified)
    log.info("Enqueued %d leads", count)
    return {"enqueued": count}
