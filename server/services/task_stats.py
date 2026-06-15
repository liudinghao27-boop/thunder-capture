"""Task queue statistics and funnel aggregations using SQLAlchemy."""

import json
from sqlalchemy import func
from datetime import datetime, timezone

from server.models import SessionLocal
from server.models.task import TaskQueue, TargetBlogger

def queue_stats(industry_slug: str = "") -> dict:
    db = SessionLocal()
    try:
        query = db.query(TaskQueue.status, func.count(TaskQueue.id)).group_by(TaskQueue.status)
        if industry_slug:
            query = query.filter(TaskQueue.industry_slug == industry_slug)
        
        stats = {status: count for status, count in query.all()}
        return {
            "total": sum(stats.values()),
            "pending": stats.get("pending", 0),
            "claimed": stats.get("claimed", 0),
            "done": stats.get("done", 0),
            "failed": stats.get("failed", 0)
        }
    finally:
        db.close()

def funnel_stats(industry_slug: str = "") -> dict:
    db = SessionLocal()
    try:
        # 1. Monitored bloggers
        bloggers_query = db.query(func.count(TargetBlogger.sec_uid)).filter(TargetBlogger.status == "active")
        if industry_slug:
            bloggers_query = bloggers_query.filter(TargetBlogger.industry_slug == industry_slug)
        monitored_bloggers = bloggers_query.scalar() or 0

        # 2. Total discovered/scraped videos (not strictly tracked in SQLAlchemy easily right now, mock or leave 0)
        discovered_videos = 0

        # 3. Queue stats for the rest
        q_stats = queue_stats(industry_slug)
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
            "conversion_rate": round((sent_success / max(total_leads, 1)) * 100, 2)
        }
    finally:
        db.close()

def replenishment_plan(
    industry_slug: str,
    *,
    target_devices: int = 30,
    per_device_daily_limit: int = 15,
    inventory_days: int = 3,
    global_daily_limit: int = 0,
    threshold_days: int = 1,
    source_limit: int = 5,
) -> dict:
    inv = inventory_stats(
        industry_slug, target_devices=target_devices, per_device_daily_limit=per_device_daily_limit,
        inventory_days=inventory_days, global_daily_limit=global_daily_limit
    )
    daily_capacity = max(1, int(inv.get("daily_send_capacity") or 1))
    threshold_pending = daily_capacity * max(1, int(threshold_days or 1))
    available = int(inv.get("available") or 0)
    target_pending = int(inv.get("target_pending") or 0)
    pending_deficit = max(0, target_pending - available)
    threshold_deficit = max(0, threshold_pending - available)
    should_replenish = available < threshold_pending or pending_deficit > 0
    recommended_sources = source_performance_stats(industry_slug, limit=source_limit)
    source_names = [
        item["source"] for item in recommended_sources
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
    target_devices: int = 30,
    per_device_daily_limit: int = 15,
    inventory_days: int = 3,
    global_daily_limit: int = 0,
) -> dict:
    stats = queue_stats(industry_slug)
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
        state = db.query(ConsumerState).filter(ConsumerState.consumer_id == consumer_id).first()
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

def get_bloggers(status: str = "active", industry_slug: str = "") -> list[dict]:
    db = SessionLocal()
    try:
        query = db.query(TargetBlogger)
        if status != "all":
            query = query.filter(TargetBlogger.status == status)
        if industry_slug:
            query = query.filter(TargetBlogger.industry_slug == industry_slug)
        
        return [
            {
                "sec_uid": b.sec_uid,
                "nickname": b.nickname,
                "uid": b.uid,
                "industry_slug": b.industry_slug,
                "source_keyword": b.source_keyword,
                "source_video_id": b.source_video_id,
                "discovered_at": b.discovered_at,
                "status": b.status
            } for b in query.all()
        ]
    finally:
        db.close()


def keyword_funnel_stats(industry_slug: str, limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(TaskQueue.source_keyword, TaskQueue.keyword, TaskQueue.status, TaskQueue.matched_categories)\
            .filter(TaskQueue.industry_slug == industry_slug).all()
    finally:
        db.close()

    buckets: dict[str, dict] = {}
    for source_keyword, keyword, status, matched_categories in rows:
        key = source_keyword or keyword or "unknown"
        if key.startswith("creator:"):
            key = "unknown"
        bucket = buckets.setdefault(
            key,
            {
                "keyword": key,
                "total": 0,
                "pending": 0,
                "claimed": 0,
                "done": 0,
                "failed": 0,
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
            },
        )
        bucket["total"] += 1
        if status in {"pending", "claimed", "done", "failed"}:
            bucket[status] += 1
        try:
            meta = json.loads(matched_categories or "{}")
        except Exception:
            meta = {}
        confidence = str(meta.get("confidence", "")).lower() if isinstance(meta, dict) else ""
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


def source_type_funnel_stats(industry_slug: str) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(TaskQueue.source_keyword, TaskQueue.status, TaskQueue.matched_categories)\
            .filter(TaskQueue.industry_slug == industry_slug).all()
    finally:
        db.close()

    buckets = {
        "target": {"type": "target", "label": "对标账号", "total": 0, "pending": 0, "claimed": 0, "done": 0, "failed": 0, "high_confidence": 0},
        "keyword": {"type": "keyword", "label": "关键词", "total": 0, "pending": 0, "claimed": 0, "done": 0, "failed": 0, "high_confidence": 0},
        "unknown": {"type": "unknown", "label": "未标记", "total": 0, "pending": 0, "claimed": 0, "done": 0, "failed": 0, "high_confidence": 0},
    }
    for source_keyword, status, matched_categories in rows:
        source = source_keyword or ""
        if source.startswith("对标:"):
            key = "target"
        elif source:
            key = "keyword"
        else:
            key = "unknown"
        bucket = buckets[key]
        bucket["total"] += 1
        if status in {"pending", "claimed", "done", "failed"}:
            bucket[status] += 1
        try:
            meta = json.loads(matched_categories or "{}")
        except Exception:
            meta = {}
        if isinstance(meta, dict) and str(meta.get("confidence", "")).lower() == "high":
            bucket["high_confidence"] += 1
    return [b for b in buckets.values() if b["total"] > 0]


def blogger_source_stats(industry_slug: str) -> dict:
    db = SessionLocal()
    try:
        rows = db.query(TargetBlogger.source_keyword, TargetBlogger.status)\
            .filter(TargetBlogger.industry_slug == industry_slug).all()
    finally:
        db.close()

    result = {
        "total": 0,
        "active": 0,
        "target": 0,
        "keyword": 0,
        "unknown": 0,
    }
    for source_keyword, status in rows:
        source = source_keyword or ""
        result["total"] += 1
        if status == "active":
            result["active"] += 1
        if source.startswith("对标:"):
            result["target"] += 1
        elif source:
            result["keyword"] += 1
        else:
            result["unknown"] += 1
    return result


def _source_type(source: str) -> str:
    if source.startswith("对标:"):
        return "target"
    if source:
        return "keyword"
    return "unknown"


def source_performance_stats(industry_slug: str, limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(TaskQueue.source_keyword, TaskQueue.keyword, TaskQueue.status, TaskQueue.matched_categories)\
            .filter(TaskQueue.industry_slug == industry_slug).all()
    finally:
        db.close()

    buckets: dict[str, dict] = {}
    for source_keyword, keyword, status, matched_categories in rows:
        source = source_keyword or keyword or "unknown"
        if source.startswith("creator:"):
            source = "unknown"
        bucket = buckets.setdefault(
            source,
            {
                "source": source,
                "type": _source_type(source if source != "unknown" else ""),
                "total": 0,
                "pending": 0,
                "claimed": 0,
                "done": 0,
                "failed": 0,
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
                "quality_score": 50,
                "collector_boost": 0,
            },
        )
        bucket["total"] += 1
        if status in {"pending", "claimed", "done", "failed"}:
            bucket[status] += 1
        try:
            meta = json.loads(matched_categories or "{}")
        except Exception:
            meta = {}
        confidence = str(meta.get("confidence", "")).lower() if isinstance(meta, dict) else ""
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

def industry_daily_quota_state(industry_slug: str) -> dict:
    from server.models.task import IndustryDailyQuota
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        quota = db.query(IndustryDailyQuota).filter(
            IndustryDailyQuota.industry_slug == industry_slug,
            IndustryDailyQuota.day == day
        ).first()
        sent = quota.sent if quota else 0
        reserved = quota.reserved if quota else 0
        return {"industry_slug": industry_slug, "day": day, "sent": sent, "reserved": reserved}
    finally:
        db.close()

def add_blogger(sec_uid: str, short_id: str, nickname: str, industry_slug: str, source_keyword: str = "", metadata: str = ""):
    from server.models import SessionLocal
    from server.models.task import TargetBlogger
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        b = db.query(TargetBlogger).filter(TargetBlogger.sec_uid == sec_uid, TargetBlogger.industry_slug == industry_slug).first()
        if not b:
            b = TargetBlogger(
                sec_uid=sec_uid, short_id=short_id, nickname=nickname,
                industry_slug=industry_slug, source_keyword=source_keyword,
                metadata_json=metadata, created_at=datetime.now(timezone.utc)
            )
            db.add(b)
            db.commit()
    finally:
        db.close()

def is_video_collected(video_id: str, sec_uid: str = "", within_hours: int = 48) -> bool:
    from server.models import SessionLocal
    from server.models.task import CollectedVideo
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    try:
        query = db.query(CollectedVideo).filter(CollectedVideo.video_id == video_id)
        if sec_uid:
            query = query.filter(CollectedVideo.source_sec_uid == sec_uid)
        v = query.first()
        if not v or not v.collected_at:
            return False
        if v.collected_at.tzinfo is None:
            v_collected_at = v.collected_at.replace(tzinfo=timezone.utc)
        else:
            v_collected_at = v.collected_at
        return (datetime.now(timezone.utc) - v_collected_at) < timedelta(hours=within_hours)
    finally:
        db.close()

def mark_video_collected(video_id: str, sec_uid: str):
    from server.models import SessionLocal
    from server.models.task import CollectedVideo
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        v = db.query(CollectedVideo).filter(CollectedVideo.video_id == video_id).first()
        if not v:
            v = CollectedVideo(video_id=video_id, source_sec_uid=sec_uid, collected_at=datetime.now(timezone.utc))
            db.add(v)
            db.commit()
    finally:
        db.close()

def get_collector_state(industry_slug: str, platform: str, key: str, default=None):
    import json
    from server.models import SessionLocal
    from server.models.task import CollectorState
    db = SessionLocal()
    try:
        state_key = f"{industry_slug}:{platform}:{key}"
        s = db.query(CollectorState).filter(CollectorState.key == state_key).first()
        if s and s.state_json:
            return json.loads(s.state_json).get("value", default)
        return default
    finally:
        db.close()

def set_collector_state(industry_slug: str, platform: str, key: str, value):
    import json
    from server.models import SessionLocal
    from server.models.task import CollectorState
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        state_key = f"{industry_slug}:{platform}:{key}"
        s = db.query(CollectorState).filter(CollectorState.key == state_key).first()
        if not s:
            s = CollectorState(key=state_key, state_json=json.dumps({"value": value}), updated_at=datetime.now(timezone.utc))
            db.add(s)
        else:
            s.state_json = json.dumps({"value": value})
            s.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

def enqueue_task(industry_slug: str, text: str, source_name: str, source_sec_uid: str, source_short_id: str, source_video_id: str, source_keyword: str = "", matched_categories: str = ""):
    from server.models import SessionLocal
    from server.models.task import TaskQueue
    from datetime import datetime, timezone
    import uuid
    db = SessionLocal()
    try:
        # Dedup: check by user_id (=source_sec_uid) + industry
        t = db.query(TaskQueue).filter(
            TaskQueue.user_id == source_sec_uid,
            TaskQueue.industry_slug == industry_slug,
            TaskQueue.status == "pending"
        ).first()
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
            )
            db.add(t)
            db.commit()
    finally:
        db.close()

def mark_target_active(sec_uid: str, industry_slug: str):
    from server.models import SessionLocal
    from server.models.task import TargetBlogger
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        b = db.query(TargetBlogger).filter(TargetBlogger.sec_uid == sec_uid, TargetBlogger.industry_slug == industry_slug).first()
        if b:
            b.status = "active"
            b.updated_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
