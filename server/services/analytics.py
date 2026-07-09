"""Analytics aggregation for keywords, devices, and reply variants."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy.orm import Session


def _parse_fetched_at(value: str | None) -> datetime:
    """Parse an ISO datetime string, falling back to UTC epoch for empty/invalid values."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.get("status") or "pending"] += 1
    return counts


def _calc_rates(sent: int, replied: int, converted: int) -> tuple[float, float]:
    reply_rate = round(replied / sent, 4) if sent else 0.0
    conversion_rate = round(converted / sent, 4) if sent else 0.0
    return reply_rate, conversion_rate


def aggregate_by_keyword(
    _industry_slug: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Aggregate TaskQueue-like rows by source_keyword.

    Sent metrics count rows whose status is ``sent``, ``done``, ``replied``,
    or ``converted``. Replied metrics include ``replied`` and ``converted``;
    conversion metrics include only ``converted``.
    """
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("source_keyword", "")].append(row)

    results = []
    for keyword, group in groups.items():
        if not keyword:
            continue
        counts = _status_counts(group)
        collected = len(group)
        sent = (
            counts.get("sent", 0)
            + counts.get("done", 0)
            + counts.get("replied", 0)
            + counts.get("converted", 0)
        )
        replied = counts.get("replied", 0) + counts.get("converted", 0)
        converted = counts.get("converted", 0)
        reply_rate, conversion_rate = _calc_rates(sent, replied, converted)
        results.append(
            {
                "keyword": keyword,
                "collected": collected,
                "sent": sent,
                "replied": replied,
                "converted": converted,
                "reply_rate": reply_rate,
                "conversion_rate": conversion_rate,
            }
        )

    return sorted(results, key=lambda r: r["conversion_rate"], reverse=True)


def aggregate_by_device(
    _industry_slug: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Aggregate TaskQueue-like rows by consumer_id (device).

    Sent metrics count rows whose status is ``sent``, ``done``, ``replied``,
    or ``converted``. Replied metrics include ``replied`` and ``converted``;
    conversion metrics include only ``converted``.
    """
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("consumer_id", "")].append(row)

    results = []
    for device_id, group in groups.items():
        if not device_id:
            continue
        counts = _status_counts(group)
        sent = (
            counts.get("sent", 0)
            + counts.get("done", 0)
            + counts.get("replied", 0)
            + counts.get("converted", 0)
        )
        replied = counts.get("replied", 0) + counts.get("converted", 0)
        converted = counts.get("converted", 0)
        failed = counts.get("failed", 0)
        reply_rate, conversion_rate = _calc_rates(sent, replied, converted)
        results.append(
            {
                "device_id": device_id,
                "sent": sent,
                "replied": replied,
                "converted": converted,
                "failed": failed,
                "reply_rate": reply_rate,
                "conversion_rate": conversion_rate,
            }
        )

    return sorted(results, key=lambda r: r["reply_rate"], reverse=True)


def query_task_rows(
    db: Session, industry_slug: str, days: int = 7, owner_user_id: str = ""
) -> list[dict[str, Any]]:
    """Query TaskQueue rows for analytics within the last N days.

    ``fetched_at`` is stored as an ISO-8601 string, which is lexicographically
    comparable. The time-window filter is pushed to the database so we do not
    pull the entire table into memory.
    """
    from server.models.task import TaskQueue

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = db.query(TaskQueue).filter(
        TaskQueue.industry_slug == industry_slug,
        TaskQueue.fetched_at >= since,
    )
    if owner_user_id:
        query = query.filter(TaskQueue.owner_user_id == owner_user_id)
    rows = query.all()
    return [
        {
            "id": r.id,
            "source_keyword": r.source_keyword or "",
            "consumer_id": r.consumer_id or "",
            "status": r.status or "pending",
            "reply_variant_id": r.reply_variant_id or "",
        }
        for r in rows
    ]
