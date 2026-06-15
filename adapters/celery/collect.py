"""Celery tasks: Data collection pipeline.

Migration path from core/discover.py run_discovery():
  1. Replace asyncio.create_subprocess_exec with Celery task chaining
  2. MediaCrawler subprocess → Celery task (with timeout, retry, monitoring)
  3. Each platform gets its own task for independent retry
"""

from __future__ import annotations

import logging
from celery import chain, group

from adapters.celery.app import app

log = logging.getLogger("thunder.celery.collect")


@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 min
    soft_time_limit=600,  # 10 min hard timeout
    time_limit=900,
)
def run_mediacrawler(self, platform: str, keywords: list[str], industry_slug: str):
    """Run MediaCrawler for a single platform.

    Args:
        platform: 'douyin' | 'xiaohongshu' | 'kuaishou'
        keywords: Search keywords
        industry_slug: Industry identifier for output routing
    """
    # TODO: Replace subprocess call with MediaCrawler Python API
    # Currently calls core/discover.py logic
    log.info("Collecting %s for %s with keywords=%s", platform, industry_slug, keywords)
    # Stub: actual implementation imports from core/discover.py
    return {"platform": platform, "industry_slug": industry_slug, "status": "collected"}


@app.task(bind=True, max_retries=2)
def run_full_collection(self, industry_slug: str, keywords: list[str], platforms: list[str] = None):
    """Orchestrate full collection pipeline: discover → classify → enqueue.

    Chains: MediaCrawler per platform → batch classify → enqueue tasks
    """
    if not platforms:
        platforms = ["douyin"]

    # Fan-out: collect all platforms in parallel
    jobs = group(
        run_mediacrawler.s(platform, keywords, industry_slug)
        for platform in platforms
    )

    # Chain: collect all → classify batch → enqueue
    pipeline = chain(
        jobs,
        # classify_batch.s(industry_slug),
        # enqueue_classified.s(),
    )
    result = pipeline.apply_async()
    return {"task_id": result.id, "industry_slug": industry_slug}
