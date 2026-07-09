"""Task queue statistics and funnel aggregations using SQLAlchemy."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, case, func, or_

from core.constants import (
    DEFAULT_DAILY_LIMIT,
    DEFAULT_LEAD_INVENTORY_DAYS,
    DEFAULT_MATRIX_TARGET_DEVICES,
    DEFAULT_REPLENISH_THRESHOLD_DAYS,
)

from server.models import SessionLocal
from server.models.task import TaskQueue, TargetBlogger

log = logging.getLogger("thunder.task_stats")


def queue_stats(industry_slug: str = "", owner_user_id: str = "") -> dict:
    db = SessionLocal()
    try:
        query = db.query(TaskQueue.status, func.count(TaskQueue.id)).group_by(
            TaskQueue.status
        )
        if industry_slug:
            query = query.filter(TaskQueue.industry_slug == industry_slug)
        owner_filter = _owner_filter(TaskQueue, owner_user_id)
        if owner_filter is not None:
            query = query.filter(owner_filter)

        stats = {status: count for status, count in query.all()}
        return {
            "total": sum(stats.values()),
            "pending": stats.get("pending", 0),
            "claimed": stats.get("claimed", 0),
            "done": stats.get("done", 0),
            "failed": stats.get("failed", 0),
        }
    finally:
        db.close()


def _owner_filter(model, owner_user_id: str):
    """Build an exact filter for owner isolation."""
    if not owner_user_id:
        return None
    column = getattr(model, "owner_user_id", None)
    if column is None:
        return None
    return column == owner_user_id


def funnel_stats(industry_slug: str = "", owner_user_id: str = "") -> dict:
    db = SessionLocal()
    try:
        # 1. Monitored bloggers
        bloggers_query = db.query(func.count(TargetBlogger.sec_uid)).filter(
            TargetBlogger.status == "active"
        )
        if industry_slug:
            bloggers_query = bloggers_query.filter(
                TargetBlogger.industry_slug == industry_slug
            )
        if owner_user_id:
            owner_filter = _owner_filter(TargetBlogger, owner_user_id)
            if owner_filter is not None:
                bloggers_query = bloggers_query.filter(owner_filter)
        monitored_bloggers = bloggers_query.scalar() or 0

        # 2. Total discovered/scraped videos (not strictly tracked in SQLAlchemy easily right now, mock or leave 0)
        discovered_videos = 0

        # 3. Queue stats for the rest
        q_stats = queue_stats(industry_slug, owner_user_id=owner_user_id)
        total_leads = q_stats["total"]
        pending = q_stats["pending"]
        sent_success = q_stats["done"]
        sent_failed = q_stats["failed"]

        return {
            "monitored_bloggers": monitored_bloggers,
            "discovered_videos": discovered_videos,
            "total_leads": total_leads,
            "pending_leads": pending,
            "sent_success": sent_success,
            "sent_failed": sent_failed,
            "conversion_rate": round((sent_success / max(total_leads, 1)) * 100, 2),
        }
    finally:
        db.close()


def replenishment_plan(
    industry_slug: str,
    *,
    target_devices: int = DEFAULT_MATRIX_TARGET_DEVICES,
    per_device_daily_limit: int = DEFAULT_DAILY_LIMIT,
    inventory_days: int = DEFAULT_LEAD_INVENTORY_DAYS,
    global_daily_limit: int = 0,
    threshold_days: int = DEFAULT_REPLENISH_THRESHOLD_DAYS,
    source_limit: int = 5,
    owner_user_id: str = "",
) -> dict:
    inv = inventory_stats(
        industry_slug,
        target_devices=target_devices,
        per_device_daily_limit=per_device_daily_limit,
        inventory_days=inventory_days,
        global_daily_limit=global_daily_limit,
        owner_user_id=owner_user_id,
    )
    daily_capacity = max(1, int(inv.get("daily_send_capacity") or 1))
    threshold_pending = daily_capacity * max(1, int(threshold_days or 1))
    available = int(inv.get("available") or 0)
    target_pending = int(inv.get("target_pending") or 0)
    pending_deficit = max(0, target_pending - available)
    threshold_deficit = max(0, threshold_pending - available)
    should_replenish = available < threshold_pending or pending_deficit > 0
    recommended_sources = source_performance_stats(
        industry_slug, limit=source_limit, owner_user_id=owner_user_id
    )
    source_names = [
        item["source"]
        for item in recommended_sources
        if item.get("source") and item.get("source") != "unknown"
    ]
    skip_discover = not (available < threshold_pending)
    return {
        "industry_slug": industry_slug,
        "inventory": inv,
        "threshold_days": max(1, int(threshold_days or 1)),
        "threshold_pending": threshold_pending,
        "threshold_deficit": threshold_deficit,
        "pending_deficit": pending_deficit,
        "should_replenish": should_replenish,
        "skip_discover": skip_discover,
        "mode": "collect_only" if skip_discover else "discover_and_collect",
        "recommended_sources": recommended_sources,
        "recommended_source_names": source_names,
        "reason": (
            f"库存仅 {inv.get('stock_days', 0)} 天，低于安全阈值 {max(1, int(threshold_days or 1))} 天"
            if available < threshold_pending
            else (
                f"目标库存缺口 {pending_deficit} 条"
                if pending_deficit > 0
                else "库存充足"
            )
        ),
    }


def inventory_stats(
    industry_slug: str,
    target_devices: int = DEFAULT_MATRIX_TARGET_DEVICES,
    per_device_daily_limit: int = DEFAULT_DAILY_LIMIT,
    inventory_days: int = DEFAULT_LEAD_INVENTORY_DAYS,
    global_daily_limit: int = 0,
    owner_user_id: str = "",
) -> dict:
    stats = queue_stats(industry_slug, owner_user_id=owner_user_id)
    pending = int(stats.get("pending", 0))
    claimed = int(stats.get("claimed", 0))
    daily_capacity = max(0, int(target_devices)) * max(0, int(per_device_daily_limit))
    if int(global_daily_limit or 0) > 0:
        daily_capacity = min(daily_capacity, int(global_daily_limit))
    target_pending = daily_capacity * max(1, int(inventory_days))
    available = pending + claimed
    stock_days = round(available / daily_capacity, 2) if daily_capacity else 0.0
    return {
        **stats,
        "available": available,
        "target_devices": target_devices,
        "per_device_daily_limit": per_device_daily_limit,
        "inventory_days": inventory_days,
        "daily_send_capacity": daily_capacity,
        "target_pending": target_pending,
        "pending_deficit": max(0, target_pending - available),
        "stock_days": stock_days,
        "ready": available >= target_pending,
    }


def get_wave_state(consumer_id: str):
    from server.models.task import ConsumerState

    db = SessionLocal()
    try:
        state = (
            db.query(ConsumerState)
            .filter(ConsumerState.consumer_id == consumer_id)
            .first()
        )
        if not state:
            return None
        return {
            "consumer_id": state.consumer_id,
            "wave_sent": state.wave_sent,
            "waves_today": state.waves_today,
            "rate_limited_at": state.rate_limited_at,
            "adaptive_limit": state.adaptive_limit,
            "last_wave_date": state.last_wave_date,
            "nurture_done_today": state.nurture_done_today,
            "daily_sent": state.daily_sent,
            "last_sent_date": state.last_sent_date,
            "daily_limit": state.daily_limit,
            "min_interval_sec": state.min_interval_sec,
        }
    finally:
        db.close()


def get_bloggers(
    status: str = "active", industry_slug: str = "", owner_user_id: str = ""
) -> list[dict]:
    db = SessionLocal()
    try:
        query = db.query(TargetBlogger)
        if status != "all":
            query = query.filter(TargetBlogger.status == status)
        if industry_slug:
            query = query.filter(TargetBlogger.industry_slug == industry_slug)
        if owner_user_id:
            owner_filter = _owner_filter(TargetBlogger, owner_user_id)
            if owner_filter is not None:
                query = query.filter(owner_filter)

        return [
            {
                "sec_uid": b.sec_uid,
                "nickname": b.nickname,
                "uid": b.uid,
                "industry_slug": b.industry_slug,
                "source_keyword": b.source_keyword,
                "source_video_id": b.source_video_id,
                "discovered_at": b.discovered_at,
                "status": b.status,
            }
            for b in query.all()
        ]
    finally:
        db.close()


def keyword_funnel_stats(
    industry_slug: str, limit: int = 20, owner_user_id: str = ""
) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    key_expr = func.coalesce(
        func.nullif(TaskQueue.source_keyword, ""),
        func.nullif(TaskQueue.keyword, ""),
        "unknown",
    )

    db = SessionLocal()
    try:
        # Aggregate status counts in the database, scoped to a rolling window.
        agg_query = (
            db.query(
                key_expr.label("key"),
                func.count(TaskQueue.id).label("total"),
                func.sum(case((TaskQueue.status == "pending", 1), else_=0)).label(
                    "pending"
                ),
                func.sum(case((TaskQueue.status == "claimed", 1), else_=0)).label(
                    "claimed"
                ),
                func.sum(case((TaskQueue.status == "done", 1), else_=0)).label("done"),
                func.sum(case((TaskQueue.status == "failed", 1), else_=0)).label(
                    "failed"
                ),
            )
            .filter(
                TaskQueue.industry_slug == industry_slug,
                TaskQueue.fetched_at >= since,
            )
            .group_by(key_expr)
        )
        if owner_user_id:
            owner_filter = _owner_filter(TaskQueue, owner_user_id)
            if owner_filter is not None:
                agg_query = agg_query.filter(owner_filter)

        buckets: dict[str, dict] = {}
        for row in agg_query:
            key = row.key
            if not key:
                key = "unknown"
            if key.startswith("creator:"):
                key = "unknown"
            buckets[key] = {
                "keyword": key,
                "total": int(row.total or 0),
                "pending": int(row.pending or 0),
                "claimed": int(row.claimed or 0),
                "done": int(row.done or 0),
                "failed": int(row.failed or 0),
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
            }

        # Confidence requires JSON parsing; only fetch the two columns needed.
        conf_query = db.query(
            key_expr.label("key"),
            TaskQueue.matched_categories,
        ).filter(
            TaskQueue.industry_slug == industry_slug,
            TaskQueue.fetched_at >= since,
        )
        if owner_user_id:
            owner_filter = _owner_filter(TaskQueue, owner_user_id)
            if owner_filter is not None:
                conf_query = conf_query.filter(owner_filter)

        for key, matched_categories in conf_query:
            key = key or "unknown"
            if key.startswith("creator:"):
                key = "unknown"
            bucket = buckets.get(key)
            if bucket is None:
                continue
            try:
                meta = json.loads(matched_categories or "{}")
            except Exception as exc:
                logging.getLogger("thunder.task_stats").debug(
                    "Failed to parse matched_categories: %s", exc
                )
                meta = {}
            confidence = (
                str(meta.get("confidence", "")).lower()
                if isinstance(meta, dict)
                else ""
            )
            if confidence in {"high", "medium", "low"}:
                bucket[f"{confidence}_confidence"] += 1

        ranked = sorted(
            buckets.values(),
            key=lambda b: (
                b["keyword"] != "unknown",
                b["pending"] + b["done"] + b["claimed"],
                b["high_confidence"],
                b["total"],
            ),
            reverse=True,
        )
        return ranked[: max(1, int(limit))]
    finally:
        db.close()


def source_type_funnel_stats(industry_slug: str, owner_user_id: str = "") -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    source_expr = func.coalesce(
        func.nullif(TaskQueue.source_keyword, ""),
        func.nullif(TaskQueue.keyword, ""),
        "",
    )

    db = SessionLocal()
    try:
        agg_query = (
            db.query(
                source_expr.label("source"),
                TaskQueue.status,
                func.count(TaskQueue.id).label("total"),
            )
            .filter(
                TaskQueue.industry_slug == industry_slug,
                TaskQueue.fetched_at >= since,
            )
            .group_by(source_expr, TaskQueue.status)
        )
        if owner_user_id:
            owner_filter = _owner_filter(TaskQueue, owner_user_id)
            if owner_filter is not None:
                agg_query = agg_query.filter(owner_filter)

        buckets: dict[str, dict[str, Any]] = {
            "target": {
                "type": "target",
                "label": "对标账号",
                "total": 0,
                "pending": 0,
                "claimed": 0,
                "done": 0,
                "failed": 0,
                "high_confidence": 0,
            },
            "keyword": {
                "type": "keyword",
                "label": "关键词",
                "total": 0,
                "pending": 0,
                "claimed": 0,
                "done": 0,
                "failed": 0,
                "high_confidence": 0,
            },
            "unknown": {
                "type": "unknown",
                "label": "未标记",
                "total": 0,
                "pending": 0,
                "claimed": 0,
                "done": 0,
                "failed": 0,
                "high_confidence": 0,
            },
        }
        for source, status, total in agg_query:
            source = source or ""
            if source.startswith("对标:"):
                key = "target"
            elif source:
                key = "keyword"
            else:
                key = "unknown"
            bucket = buckets[key]
            bucket["total"] += int(total or 0)
            if status in {"pending", "claimed", "done", "failed"}:
                bucket[status] += int(total or 0)

        # Confidence still requires JSON parsing; scoped to the same window.
        conf_query = db.query(
            source_expr.label("source"),
            TaskQueue.matched_categories,
        ).filter(
            TaskQueue.industry_slug == industry_slug,
            TaskQueue.fetched_at >= since,
        )
        if owner_user_id:
            owner_filter = _owner_filter(TaskQueue, owner_user_id)
            if owner_filter is not None:
                conf_query = conf_query.filter(owner_filter)

        for source, matched_categories in conf_query:
            source = source or ""
            if source.startswith("对标:"):
                key = "target"
            elif source:
                key = "keyword"
            else:
                key = "unknown"
            bucket = buckets[key]
            try:
                meta = json.loads(matched_categories or "{}")
            except Exception:
                meta = {}
            if (
                isinstance(meta, dict)
                and str(meta.get("confidence", "")).lower() == "high"
            ):
                bucket["high_confidence"] += 1

        return [b for b in buckets.values() if b["total"] > 0]
    finally:
        db.close()


def blogger_source_stats(industry_slug: str, owner_user_id: str = "") -> dict:
    source_expr = func.coalesce(func.nullif(TargetBlogger.source_keyword, ""), "")
    db = SessionLocal()
    try:
        query = db.query(
            func.count(TargetBlogger.sec_uid).label("total"),
            func.sum(case((TargetBlogger.status == "active", 1), else_=0)).label(
                "active"
            ),
            func.sum(case((source_expr.like("对标:%"), 1), else_=0)).label("target"),
            func.sum(
                case(
                    (and_(source_expr != "", source_expr.notlike("对标:%")), 1), else_=0
                )
            ).label("keyword"),
            func.sum(
                case((or_(source_expr == "", source_expr.is_(None)), 1), else_=0)
            ).label("unknown"),
        ).filter(TargetBlogger.industry_slug == industry_slug)
        if owner_user_id:
            owner_filter = _owner_filter(TargetBlogger, owner_user_id)
            if owner_filter is not None:
                query = query.filter(owner_filter)
        row = query.one()
    finally:
        db.close()

    return {
        "total": int(row.total or 0),
        "active": int(row.active or 0),
        "target": int(row.target or 0),
        "keyword": int(row.keyword or 0),
        "unknown": int(row.unknown or 0),
    }


def _source_type(source: str) -> str:
    if source.startswith("对标:"):
        return "target"
    if source:
        return "keyword"
    return "unknown"


def source_performance_stats(
    industry_slug: str, limit: int = 20, owner_user_id: str = ""
) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    source_expr = func.coalesce(
        func.nullif(TaskQueue.source_keyword, ""),
        func.nullif(TaskQueue.keyword, ""),
        "unknown",
    )

    db = SessionLocal()
    try:
        agg_query = (
            db.query(
                source_expr.label("source"),
                func.count(TaskQueue.id).label("total"),
                func.sum(case((TaskQueue.status == "pending", 1), else_=0)).label(
                    "pending"
                ),
                func.sum(case((TaskQueue.status == "claimed", 1), else_=0)).label(
                    "claimed"
                ),
                func.sum(case((TaskQueue.status == "done", 1), else_=0)).label("done"),
                func.sum(case((TaskQueue.status == "failed", 1), else_=0)).label(
                    "failed"
                ),
            )
            .filter(
                TaskQueue.industry_slug == industry_slug,
                TaskQueue.fetched_at >= since,
            )
            .group_by(source_expr)
        )
        if owner_user_id:
            owner_filter = _owner_filter(TaskQueue, owner_user_id)
            if owner_filter is not None:
                agg_query = agg_query.filter(owner_filter)

        buckets: dict[str, dict] = {}
        for row in agg_query:
            source = row.source
            if not source:
                source = "unknown"
            if source.startswith("creator:"):
                source = "unknown"
            buckets[source] = {
                "source": source,
                "type": _source_type(source if source != "unknown" else ""),
                "total": int(row.total or 0),
                "pending": int(row.pending or 0),
                "claimed": int(row.claimed or 0),
                "done": int(row.done or 0),
                "failed": int(row.failed or 0),
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
                "quality_score": 50,
                "collector_boost": 0,
            }

        conf_query = db.query(
            source_expr.label("source"),
            TaskQueue.matched_categories,
        ).filter(
            TaskQueue.industry_slug == industry_slug,
            TaskQueue.fetched_at >= since,
        )
        if owner_user_id:
            owner_filter = _owner_filter(TaskQueue, owner_user_id)
            if owner_filter is not None:
                conf_query = conf_query.filter(owner_filter)

        for source, matched_categories in conf_query:
            source = source or "unknown"
            if source.startswith("creator:"):
                source = "unknown"
            bucket = buckets.get(source)
            if bucket is None:
                continue
            try:
                meta = json.loads(matched_categories or "{}")
            except Exception:
                meta = {}
            confidence = (
                str(meta.get("confidence", "")).lower()
                if isinstance(meta, dict)
                else ""
            )
            if confidence in {"high", "medium", "low"}:
                bucket[f"{confidence}_confidence"] += 1

        for bucket in buckets.values():
            total = max(1, int(bucket["total"]))
            done_rate = bucket["done"] / total
            failed_rate = bucket["failed"] / total
            high_rate = bucket["high_confidence"] / total
            medium_rate = bucket["medium_confidence"] / total
            low_rate = bucket["low_confidence"] / total
            score = (
                50
                + done_rate * 25
                - failed_rate * 25
                + high_rate * 22
                + medium_rate * 8
                - low_rate * 12
            )
            if total < 5:
                score = 50 + ((score - 50) * 0.55)
            bucket["quality_score"] = round(max(0, min(100, score)), 1)
            bucket["collector_boost"] = round((bucket["quality_score"] - 50) / 2, 1)

        ranked = sorted(
            buckets.values(),
            key=lambda b: (
                b["source"] != "unknown",
                b["quality_score"],
                b["done"] + b["pending"] + b["claimed"],
                b["total"],
            ),
            reverse=True,
        )
        return ranked[: max(1, int(limit))]
    finally:
        db.close()


def industry_daily_quota_state(industry_slug: str, owner_user_id: str = "") -> dict:
    from server.models.task import IndustryDailyQuota

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        query = db.query(IndustryDailyQuota).filter(
            IndustryDailyQuota.industry_slug == industry_slug,
            IndustryDailyQuota.day == day,
        )
        if owner_user_id:
            owner_filter = _owner_filter(IndustryDailyQuota, owner_user_id)
            if owner_filter is not None:
                query = query.filter(owner_filter)
        quota = query.first()
        sent = quota.sent if quota else 0
        reserved = quota.reserved if quota else 0
        return {
            "industry_slug": industry_slug,
            "day": day,
            "sent": sent,
            "reserved": reserved,
        }
    finally:
        db.close()


def add_blogger(
    sec_uid: str,
    short_id: str,
    nickname: str,
    industry_slug: str,
    source_keyword: str = "",
    metadata: str = "",
    owner_user_id: str = "",
):
    from server.models import SessionLocal
    from server.models.task import TargetBlogger
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        b = (
            db.query(TargetBlogger)
            .filter(
                TargetBlogger.sec_uid == sec_uid,
                TargetBlogger.industry_slug == industry_slug,
                TargetBlogger.owner_user_id == owner_user_id,
            )
            .first()
        )
        if not b:
            b = TargetBlogger(
                sec_uid=sec_uid,
                nickname=nickname,
                industry_slug=industry_slug,
                source_keyword=source_keyword,
                owner_user_id=owner_user_id,
                discovered_at=datetime.now(timezone.utc).isoformat(),
            )
            db.add(b)
            db.commit()
    finally:
        db.close()


def _parse_dt(value) -> "datetime | None":
    from datetime import datetime, timezone

    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_video_collected(
    aweme_id: str, sec_uid: str = "", within_hours: int = 48, owner_user_id: str = ""
) -> bool:
    from server.models import SessionLocal
    from server.models.task import CollectedVideo
    from datetime import datetime, timezone, timedelta

    db = SessionLocal()
    try:
        query = db.query(CollectedVideo).filter(CollectedVideo.aweme_id == aweme_id)
        if sec_uid:
            query = query.filter(CollectedVideo.source_sec_uid == sec_uid)
        if owner_user_id:
            owner_filter = _owner_filter(CollectedVideo, owner_user_id)
            if owner_filter is not None:
                query = query.filter(owner_filter)
        v = query.first()
        if not v:
            return False
        v_collected_at = _parse_dt(v.collected_at)
        if v_collected_at is None:
            return False
        return (datetime.now(timezone.utc) - v_collected_at) < timedelta(
            hours=within_hours
        )
    finally:
        db.close()


def mark_video_collected(aweme_id: str, sec_uid: str, owner_user_id: str = ""):
    from server.models import SessionLocal
    from server.models.task import CollectedVideo
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        query = db.query(CollectedVideo).filter(
            CollectedVideo.aweme_id == aweme_id,
            CollectedVideo.source_sec_uid == sec_uid,
        )
        if owner_user_id:
            owner_filter = _owner_filter(CollectedVideo, owner_user_id)
            if owner_filter is not None:
                query = query.filter(owner_filter)
        v = query.first()
        if not v:
            v = CollectedVideo(
                aweme_id=aweme_id,
                source_sec_uid=sec_uid,
                owner_user_id=owner_user_id,
                collected_at=datetime.now(timezone.utc).isoformat(),
            )
            db.add(v)
            db.commit()
    finally:
        db.close()


def get_collector_state(
    industry_slug: str, platform: str, key: str, default=None, owner_user_id: str = ""
):
    import json
    from server.models import SessionLocal
    from server.models.task import CollectorState

    db = SessionLocal()
    try:
        query = db.query(CollectorState).filter(
            CollectorState.industry_slug == industry_slug,
            CollectorState.platform == platform,
            CollectorState.key == key,
        )
        if owner_user_id:
            owner_filter = _owner_filter(CollectorState, owner_user_id)
            if owner_filter is not None:
                query = query.filter(owner_filter)
        s = query.first()
        if s and s.value:
            try:
                return json.loads(str(s.value))
            except Exception:
                return default
        return default
    finally:
        db.close()


def set_collector_state(
    industry_slug: str,
    platform: str,
    key: str,
    value,
    owner_user_id: str = "",
):
    import json
    from server.models import SessionLocal
    from server.models.task import CollectorState
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        query = db.query(CollectorState).filter(
            CollectorState.industry_slug == industry_slug,
            CollectorState.platform == platform,
            CollectorState.key == key,
        )
        if owner_user_id:
            owner_filter = _owner_filter(CollectorState, owner_user_id)
            if owner_filter is not None:
                query = query.filter(owner_filter)
        s = query.first()
        if not s:
            s = CollectorState(
                industry_slug=industry_slug,
                platform=platform,
                key=key,
                owner_user_id=owner_user_id,
                value=json.dumps(value),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            db.add(s)
        else:
            s.value = json.dumps(value)  # type: ignore[assignment]
            s.updated_at = datetime.now(timezone.utc).isoformat()  # type: ignore[assignment]
        db.commit()
    finally:
        db.close()


def enqueue_task(
    industry_slug: str,
    text: str,
    source_name: str,
    source_sec_uid: str,
    source_short_id: str,
    source_video_id: str,
    source_keyword: str = "",
    matched_categories: str = "",
    owner_user_id: str = "",
):
    from server.models import SessionLocal
    from server.models.task import TaskQueue
    from datetime import datetime, timezone
    import uuid

    db = SessionLocal()
    try:
        # Dedup: check by user_id (=source_sec_uid) + industry
        t = (
            db.query(TaskQueue)
            .filter(
                TaskQueue.user_id == source_sec_uid,
                TaskQueue.industry_slug == industry_slug,
                TaskQueue.status == "pending",
            )
            .first()
        )
        if not t:
            t = TaskQueue(
                industry_slug=industry_slug,
                text=text,
                user_name=source_name,
                user_id=source_sec_uid,
                short_id=source_short_id,
                video_id=source_video_id or "",
                comment_id=source_short_id or str(uuid.uuid4())[:12],
                source_keyword=source_keyword,
                matched_categories=matched_categories,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                status="pending",
                owner_user_id=owner_user_id,
            )
            db.add(t)
            db.commit()
    finally:
        db.close()


def enqueue_tasks_batch_result(comments: list[dict]) -> dict:
    """Bulk-insert classified comments and return insert/dedup metrics."""
    from datetime import datetime, timezone
    from uuid import uuid4
    from server.models import SessionLocal, engine
    from server.models.task import TaskQueue

    if not comments:
        return {"received": 0, "valid": 0, "inserted": 0, "duplicates": 0, "invalid": 0}

    received = len(comments)
    invalid = 0
    values = []
    for comment in comments:
        text = str(comment.get("text", "")).strip()
        source_sec_uid = str(comment.get("source_sec_uid", "")).strip()
        source_video_id = str(comment.get("source_video_id", "")).strip()
        if not text or not source_sec_uid:
            invalid += 1
            continue

        matched = comment.get("matched_categories", {})
        if isinstance(matched, dict):
            matched = json.dumps(matched, ensure_ascii=False)

        values.append(
            {
                "industry_slug": str(comment.get("industry_slug", "")),
                "platform": str(
                    comment.get("source_platform")
                    or comment.get("platform")
                    or "douyin"
                ),
                "text": text,
                "user_name": str(comment.get("source_name", "")),
                "user_id": source_sec_uid,
                "short_id": str(comment.get("source_short_id", "")),
                "video_id": source_video_id or "",
                "comment_id": str(comment.get("source_short_id", ""))
                or str(uuid4())[:12],
                "source_keyword": str(comment.get("source_keyword", "")),
                "source_creator": str(comment.get("source_creator", "")),
                "source_video_desc": str(comment.get("source_video_desc", "")),
                "matched_categories": matched or "[]",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                "owner_user_id": str(comment.get("owner_user_id", "")),
                "job_id": str(comment.get("job_id", "")),
            }
        )

    valid = len(values)
    if not values:
        return {
            "received": received,
            "valid": 0,
            "inserted": 0,
            "duplicates": 0,
            "invalid": invalid,
        }

    db = SessionLocal()
    try:
        dialect = engine.dialect.name
        stmt: Any = None
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = (
                pg_insert(TaskQueue)
                .values(values)
                .on_conflict_do_nothing(index_elements=["comment_id", "video_id"])
            )
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = (
                sqlite_insert(TaskQueue)
                .values(values)
                .on_conflict_do_nothing(index_elements=["comment_id", "video_id"])
            )
        else:
            db.close()
            inserted = 0
            seen_keys = set()
            for comment in comments:
                key = (
                    str(comment.get("source_short_id", "")),
                    str(comment.get("source_video_id", "")),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                matched = comment.get("matched_categories", {})
                if isinstance(matched, dict):
                    matched = json.dumps(matched, ensure_ascii=False)
                enqueue_task(
                    industry_slug=comment.get("industry_slug", ""),
                    text=comment.get("text", ""),
                    source_name=comment.get("source_name", ""),
                    source_sec_uid=comment.get("source_sec_uid", ""),
                    source_short_id=comment.get("source_short_id", ""),
                    source_video_id=comment.get("source_video_id", ""),
                    source_keyword=comment.get("source_keyword", ""),
                    matched_categories=matched,
                    owner_user_id=str(comment.get("owner_user_id", "")),
                )
                inserted += 1
            return {
                "received": received,
                "valid": valid,
                "inserted": inserted,
                "duplicates": max(valid - inserted, 0),
                "invalid": invalid,
            }

        result = db.execute(stmt)
        db.commit()
        inserted = int(getattr(result, "rowcount", 0) or 0)
        duplicates = max(valid - inserted, 0)
        log.info("  批量入队: %s 条(去重 %s)", inserted, duplicates)
        return {
            "received": received,
            "valid": valid,
            "inserted": inserted,
            "duplicates": duplicates,
            "invalid": invalid,
        }
    except Exception as e:
        db.rollback()
        log.warning("批量入队失败: %s", e)
        return {
            "received": received,
            "valid": valid,
            "inserted": 0,
            "duplicates": valid,
            "invalid": invalid,
        }
    finally:
        db.close()


def enqueue_tasks_batch(comments: list[dict]) -> int:
    """Backward-compatible wrapper returning only inserted count."""
    return int(enqueue_tasks_batch_result(comments).get("inserted", 0))


def mark_target_active(sec_uid: str, industry_slug: str, owner_user_id: str = ""):
    from server.models import SessionLocal
    from server.models.task import TargetBlogger

    db = SessionLocal()
    try:
        b = (
            db.query(TargetBlogger)
            .filter(
                TargetBlogger.sec_uid == sec_uid,
                TargetBlogger.industry_slug == industry_slug,
                TargetBlogger.owner_user_id == owner_user_id,
            )
            .first()
        )
        if b:
            b.status = "active"  # type: ignore[assignment]
            db.commit()
    finally:
        db.close()


def mark_target_inactive(sec_uid: str, industry_slug: str, owner_user_id: str = ""):
    from server.models import SessionLocal
    from server.models.task import TargetBlogger

    db = SessionLocal()
    try:
        b = (
            db.query(TargetBlogger)
            .filter(
                TargetBlogger.sec_uid == sec_uid,
                TargetBlogger.industry_slug == industry_slug,
                TargetBlogger.owner_user_id == owner_user_id,
            )
            .first()
        )
        if b:
            b.status = "paused"  # type: ignore[assignment]
            db.commit()
    finally:
        db.close()
