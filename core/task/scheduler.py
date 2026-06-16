"""Matrix task scheduler with SQLAlchemy PostgreSQL backend."""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from server.models import SessionLocal
from server.models.task import TaskQueue, IndustryDailyQuota

log = logging.getLogger("thunder.scheduler")

@dataclass
class ClaimedTask:
    task: dict | None
    reserved: bool = False
    reason: str = ""

def _now():
    return datetime.now(timezone.utc).isoformat()

class MatrixTaskScheduler:
    def __init__(
        self,
        *,
        industry_slug: str,
        owner_user_id: str = "",
        global_daily_limit: int = 0,
        daily_send_max: int = 0,
        job_id: str = "",
    ):
        self.industry_slug = industry_slug
        self.owner_user_id = owner_user_id
        self.global_daily_limit = int(global_daily_limit or 0)
        self.daily_send_max = int(daily_send_max or 0)
        self.job_id = job_id
        self._db = None

    def _get_db(self):
        if not self._db:
            self._db = SessionLocal()
        return self._db

    def close(self):
        if self._db:
            self._db.close()
            self._db = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def claim_for_device(self, device_id: str) -> ClaimedTask:
        db = self._get_db()
        try:
            # 1. Check reservation
            if self.global_daily_limit > 0:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                quota = db.query(IndustryDailyQuota).filter(
                    IndustryDailyQuota.industry_slug == self.industry_slug,
                    IndustryDailyQuota.day == day
                ).with_for_update().first()
                
                if quota and (quota.sent + quota.reserved >= self.global_daily_limit):
                    db.rollback()
                    return ClaimedTask(None, reserved=False, reason="global_daily_limit")
                
                if not quota:
                    quota = IndustryDailyQuota(industry_slug=self.industry_slug, day=day, sent=0, reserved=1)
                    db.add(quota)
                else:
                    quota.reserved += 1
                db.flush()

            # 2. Check industry daily max
            if self.daily_send_max > 0:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                quota = db.query(IndustryDailyQuota).filter(
                    IndustryDailyQuota.industry_slug == self.industry_slug,
                    IndustryDailyQuota.day == day
                ).with_for_update().first()
                if quota and (quota.sent + quota.reserved >= self.daily_send_max):
                    db.rollback()
                    return ClaimedTask(None, reserved=False, reason="industry_daily_limit_reached")

            # 3. Claim Task
            query = db.query(TaskQueue).filter(
                TaskQueue.status == "pending",
                TaskQueue.industry_slug == self.industry_slug
            )
            if self.owner_user_id:
                query = query.filter(TaskQueue.owner_user_id == self.owner_user_id)
            
            # Note: with_for_update(skip_locked=True) is postgres specific, SQLite might just lock. 
            # In SQLAlchemy, skip_locked=True is silently ignored on sqlite.
            task = query.order_by(TaskQueue.id).with_for_update(skip_locked=True).first()
            
            if not task:
                db.rollback()
                self.release() # Release quota
                return ClaimedTask(None, reserved=False, reason="no_task")
            
            # Claim it
            claim_token = str(uuid.uuid4())
            task.status = "claimed"
            task.consumer_id = device_id
            task.claim_token = claim_token
            task.claimed_at = _now()
            task.job_id = self.job_id
            
            db.commit()
            
            task_dict = {
                "id": task.id,
                "video_id": task.video_id,
                "comment_id": task.comment_id,
                "text": task.text,
                "user_name": task.user_name,
                "user_id": task.user_id,
                "sec_uid": getattr(task, "user_id", ""),  # Fallback mappings
                "short_id": getattr(task, "short_id", ""),
                "douyin_id": getattr(task, "douyin_id", ""),
                "unique_id": getattr(task, "unique_id", ""),
                "claim_token": claim_token,
                "status": "claimed"
            }
            return ClaimedTask(task_dict, reserved=True)
            
        except Exception as e:
            db.rollback()
            log.exception("claim_for_device failed")
            return ClaimedTask(None, reserved=False, reason=f"error: {str(e)}")

    def commit(self):
        if self.global_daily_limit <= 0:
            return
        db = self._get_db()
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            quota = db.query(IndustryDailyQuota).filter(
                IndustryDailyQuota.industry_slug == self.industry_slug,
                IndustryDailyQuota.day == day
            ).with_for_update().first()
            if quota and quota.reserved > 0:
                quota.reserved -= 1
                quota.sent += 1
                db.commit()
        except Exception:
            db.rollback()

    def release(self):
        if self.global_daily_limit <= 0:
            return
        db = self._get_db()
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            quota = db.query(IndustryDailyQuota).filter(
                IndustryDailyQuota.industry_slug == self.industry_slug,
                IndustryDailyQuota.day == day
            ).with_for_update().first()
            if quota and quota.reserved > 0:
                quota.reserved -= 1
                db.commit()
        except Exception:
            db.rollback()

    def mark_task_done(self, task_id: int, consumer_id: str, ai_reply: str = "", claim_token: str = ""):
        db = self._get_db()
        try:
            task = db.query(TaskQueue).filter(
                TaskQueue.id == task_id,
                TaskQueue.status == "claimed",
                TaskQueue.consumer_id == consumer_id,
                TaskQueue.claim_token == claim_token
            ).first()
            if task:
                task.status = "done"
                task.processed_at = _now()
                task.ai_reply = ai_reply
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False

    def mark_task_failed(self, task_id: int, consumer_id: str, error: str = "", claim_token: str = ""):
        db = self._get_db()
        try:
            task = db.query(TaskQueue).filter(
                TaskQueue.id == task_id,
                TaskQueue.status == "claimed",
                TaskQueue.consumer_id == consumer_id,
                TaskQueue.claim_token == claim_token
            ).first()
            if task:
                task.status = "failed"
                task.processed_at = _now()
                task.error = error[:500]
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False

    def mark_task_retry(self, task_id: int, consumer_id: str, error: str = "", claim_token: str = ""):
        db = self._get_db()
        try:
            task = db.query(TaskQueue).filter(
                TaskQueue.id == task_id,
                TaskQueue.status == "claimed",
                TaskQueue.consumer_id == consumer_id,
                TaskQueue.claim_token == claim_token
            ).first()
            if task:
                current_retries = task.retry_count or 0
                cooldown_minutes = 5 * (3 ** current_retries)
                retry_after = (datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)).isoformat()
                
                task.status = "pending"
                task.consumer_id = None
                task.claim_token = None
                task.claimed_at = None
                task.job_id = ""
                task.error = error[:200]
                task.retry_count = current_retries + 1
                task.retry_after = retry_after
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False
            
    def release_task_claim(self, task_id: int, consumer_id: str, error: str = "", claim_token: str = ""):
        db = self._get_db()
        try:
            task = db.query(TaskQueue).filter(
                TaskQueue.id == task_id,
                TaskQueue.status == "claimed",
                TaskQueue.consumer_id == consumer_id,
                TaskQueue.claim_token == claim_token
            ).first()
            if task:
                task.status = "pending"
                task.consumer_id = None
                task.claim_token = None
                task.claimed_at = None
                task.job_id = ""
                task.error = error[:200]
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False
