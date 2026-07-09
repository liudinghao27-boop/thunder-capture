"""Matrix task scheduler with SQLAlchemy PostgreSQL backend."""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from server.models import SessionLocal
from server.models.task import ConsumerState, IndustryDailyQuota, TaskQueue

log = logging.getLogger("thunder.scheduler")


@dataclass
class ClaimedTask:
    task: dict | None
    reserved: bool = False
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.task is not None and self.reserved

    @property
    def task_id(self) -> int:
        return self.task["id"] if self.task else 0


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
        device_daily_limit: int = 0,
        hourly_send_limit: int = 0,
        job_id: str = "",
    ):
        self.industry_slug = industry_slug
        self.owner_user_id = owner_user_id
        self.global_daily_limit = int(global_daily_limit or 0)
        self.daily_send_max = int(daily_send_max or 0)
        self.device_daily_limit = int(device_daily_limit or 0)
        self.hourly_send_limit = int(hourly_send_limit or 0)
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
            if self._device_daily_limit_reached(db, device_id):
                return ClaimedTask(
                    None, reserved=False, reason="device_daily_limit_reached"
                )
            if self._device_hourly_limit_reached(db, device_id):
                return ClaimedTask(
                    None, reserved=False, reason="device_hourly_limit_reached"
                )

            limits = [
                limit
                for limit in (self.global_daily_limit, self.daily_send_max)
                if limit > 0
            ]
            effective_limit = min(limits) if limits else 0
            if effective_limit:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self._ensure_quota_row(db, day)
                quota_update = db.execute(
                    update(IndustryDailyQuota)
                    .where(
                        IndustryDailyQuota.industry_slug == self.industry_slug,
                        IndustryDailyQuota.owner_user_id == self.owner_user_id,
                        IndustryDailyQuota.day == day,
                        IndustryDailyQuota.sent + IndustryDailyQuota.reserved
                        < effective_limit,
                    )
                    .values(reserved=IndustryDailyQuota.reserved + 1)
                )
                if quota_update.rowcount != 1:
                    db.rollback()
                    reason = (
                        "global_daily_limit"
                        if self.global_daily_limit == effective_limit
                        else "industry_daily_limit_reached"
                    )
                    return ClaimedTask(None, reserved=False, reason=reason)

            filters = [
                TaskQueue.status == "pending",
                TaskQueue.industry_slug == self.industry_slug,
                TaskQueue.owner_user_id == self.owner_user_id,
            ]
            candidates = (
                db.query(TaskQueue)
                .filter(*filters)
                .order_by(TaskQueue.id)
                .limit(100)
                .all()
            )
            ready_candidates = [
                task for task in candidates if self._retry_after_ready(task.retry_after)
            ]
            if not ready_candidates:
                db.rollback()
                return ClaimedTask(None, reserved=False, reason="no_task")

            for candidate in ready_candidates:
                token_suffix = str(uuid.uuid4())
                claim_token = (
                    f"{self.job_id}:{token_suffix}" if self.job_id else token_suffix
                )
                claimed_at = _now()
                claimed_id = db.execute(
                    update(TaskQueue)
                    .where(TaskQueue.id == candidate.id, TaskQueue.status == "pending")
                    .values(
                        status="claimed",
                        consumer_id=device_id,
                        claim_token=claim_token,
                        claimed_at=claimed_at,
                        job_id=self.job_id,
                    )
                    .returning(TaskQueue.id)
                ).scalar_one_or_none()

                if claimed_id is None:
                    continue

                task = db.query(TaskQueue).filter(TaskQueue.id == claimed_id).one()
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
                    "status": "claimed",
                }
                db.commit()
                return ClaimedTask(task_dict, reserved=True)

            db.rollback()
            return ClaimedTask(None, reserved=False, reason="no_task")

        except Exception as e:
            db.rollback()
            log.exception("claim_for_device failed")
            return ClaimedTask(None, reserved=False, reason=f"error: {str(e)}")

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _now_dt(self) -> datetime:
        return datetime.now(timezone.utc)

    def _parse_dt(self, value: str):
        if not value:
            return None
        normalized = str(value).strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _retry_after_ready(self, value: str | None) -> bool:
        if not value:
            return True
        parsed = self._parse_dt(str(value))
        if parsed is None:
            log.warning(
                "Ignoring invalid retry_after value for %s: %r",
                self.industry_slug,
                value,
            )
            return True
        return parsed <= self._now_dt()

    def _device_daily_limit_reached(self, db, device_id: str) -> bool:
        if self.device_daily_limit <= 0:
            return False
        today = self._today()
        state = (
            db.query(ConsumerState)
            .filter(
                ConsumerState.consumer_id == device_id,
                ConsumerState.owner_user_id == self.owner_user_id,
            )
            .first()
        )
        if state is None:
            return False
        if state.last_sent_date != today:
            return False
        return int(state.daily_sent or 0) >= self.device_daily_limit

    def _device_hourly_limit_reached(self, db, device_id: str) -> bool:
        if self.hourly_send_limit <= 0:
            return False
        state = (
            db.query(ConsumerState)
            .filter(
                ConsumerState.consumer_id == device_id,
                ConsumerState.owner_user_id == self.owner_user_id,
            )
            .first()
        )
        if state is None:
            return False
        started_at = self._parse_dt(state.rate_limited_at or "")
        if started_at is None:
            state.wave_sent = 0
            state.rate_limited_at = ""
            return False
        if self._now_dt() - started_at >= timedelta(hours=1):
            state.wave_sent = 0
            state.rate_limited_at = ""
            db.commit()
            return False
        return int(state.wave_sent or 0) >= self.hourly_send_limit

    def _record_device_send_success(self, db, device_id: str) -> None:
        today = self._today()
        now = self._now_dt()
        state = (
            db.query(ConsumerState)
            .filter(
                ConsumerState.consumer_id == device_id,
                ConsumerState.owner_user_id == self.owner_user_id,
            )
            .first()
        )
        if state is None:
            state = ConsumerState(
                consumer_id=device_id,
                owner_user_id=self.owner_user_id,
                daily_limit=self.device_daily_limit or 0,
                daily_sent=0,
                total_sent=0,
            )
            db.add(state)
            db.flush()
        if state.last_sent_date != today:
            state.daily_sent = 0
            state.last_sent_date = today
        elif not state.last_sent_date:
            state.last_sent_date = today
        state.daily_sent = int(state.daily_sent or 0) + 1
        state.total_sent = int(state.total_sent or 0) + 1
        if self.device_daily_limit > 0:
            state.daily_limit = self.device_daily_limit
        if self.hourly_send_limit > 0:
            started_at = self._parse_dt(state.rate_limited_at or "")
            if started_at is None or now - started_at >= timedelta(hours=1):
                state.rate_limited_at = now.isoformat()
                state.wave_sent = 0
            state.wave_sent = int(state.wave_sent or 0) + 1
            state.last_wave_date = today

    def _ensure_quota_row(self, db, day: str) -> None:
        values = {
            "industry_slug": self.industry_slug,
            "owner_user_id": self.owner_user_id,
            "day": day,
            "sent": 0,
            "reserved": 0,
        }
        dialect = db.get_bind().dialect.name
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            sqlite_statement = (
                sqlite_insert(IndustryDailyQuota)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["owner_user_id", "industry_slug", "day"]
                )
            )
            db.execute(sqlite_statement)
            return
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as postgresql_insert

            postgresql_statement = (
                postgresql_insert(IndustryDailyQuota)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["owner_user_id", "industry_slug", "day"]
                )
            )
            db.execute(postgresql_statement)
            return
        quota = (
            db.query(IndustryDailyQuota)
            .filter(
                IndustryDailyQuota.industry_slug == self.industry_slug,
                IndustryDailyQuota.owner_user_id == self.owner_user_id,
                IndustryDailyQuota.day == day,
            )
            .first()
        )
        if quota is None:
            try:
                db.add(IndustryDailyQuota(**values))
                db.flush()
            except IntegrityError:
                db.rollback()
                existing = (
                    db.query(IndustryDailyQuota)
                    .filter(
                        IndustryDailyQuota.industry_slug == self.industry_slug,
                        IndustryDailyQuota.owner_user_id == self.owner_user_id,
                        IndustryDailyQuota.day == day,
                    )
                    .first()
                )
                if existing is None:
                    raise

    def commit(self):
        if self.global_daily_limit <= 0 and self.daily_send_max <= 0:
            return
        db = self._get_db()
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = db.execute(
                update(IndustryDailyQuota)
                .where(
                    IndustryDailyQuota.industry_slug == self.industry_slug,
                    IndustryDailyQuota.owner_user_id == self.owner_user_id,
                    IndustryDailyQuota.day == day,
                    IndustryDailyQuota.reserved > 0,
                )
                .values(
                    reserved=IndustryDailyQuota.reserved - 1,
                    sent=IndustryDailyQuota.sent + 1,
                )
            )
            if result.rowcount:
                db.commit()
        except Exception:
            db.rollback()

    def release(self):
        if self.global_daily_limit <= 0 and self.daily_send_max <= 0:
            return
        db = self._get_db()
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = db.execute(
                update(IndustryDailyQuota)
                .where(
                    IndustryDailyQuota.industry_slug == self.industry_slug,
                    IndustryDailyQuota.owner_user_id == self.owner_user_id,
                    IndustryDailyQuota.day == day,
                    IndustryDailyQuota.reserved > 0,
                )
                .values(reserved=IndustryDailyQuota.reserved - 1)
            )
            if result.rowcount:
                db.commit()
        except Exception:
            db.rollback()

    def mark_task_done(
        self,
        task_id: int,
        consumer_id: str,
        ai_reply: str = "",
        claim_token: str = "",
        reply_variant_id: str = "",
    ):
        db = self._get_db()
        try:
            task = (
                db.query(TaskQueue)
                .filter(
                    TaskQueue.id == task_id,
                    TaskQueue.status == "claimed",
                    TaskQueue.consumer_id == consumer_id,
                    TaskQueue.claim_token == claim_token,
                )
                .first()
            )
            if task:
                task.status = "done"
                task.processed_at = _now()
                task.ai_reply = ai_reply
                if reply_variant_id:
                    task.reply_variant_id = reply_variant_id
                self._record_device_send_success(db, consumer_id)
                db.commit()
                self.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False

    def commit_task(
        self,
        task_id: int,
        consumer_id: str,
        status: str,
        message: str = "",
        claim_token: str = "",
        reply_variant_id: str = "",
    ):
        if status == "done":
            return self.mark_task_done(
                task_id,
                consumer_id,
                ai_reply=message,
                claim_token=claim_token,
                reply_variant_id=reply_variant_id,
            )
        if status == "fail":
            return self.mark_task_failed(
                task_id, consumer_id, error=message, claim_token=claim_token
            )
        return False

    def mark_task_failed(
        self, task_id: int, consumer_id: str, error: str = "", claim_token: str = ""
    ):
        db = self._get_db()
        try:
            task = (
                db.query(TaskQueue)
                .filter(
                    TaskQueue.id == task_id,
                    TaskQueue.status == "claimed",
                    TaskQueue.consumer_id == consumer_id,
                    TaskQueue.claim_token == claim_token,
                )
                .first()
            )
            if task:
                task.status = "failed"
                task.processed_at = _now()
                task.error = error[:500]
                db.commit()
                self.release()
                return True
            return False
        except Exception:
            db.rollback()
            return False

    def mark_task_retry(
        self, task_id: int, consumer_id: str, error: str = "", claim_token: str = ""
    ):
        db = self._get_db()
        try:
            task = (
                db.query(TaskQueue)
                .filter(
                    TaskQueue.id == task_id,
                    TaskQueue.status == "claimed",
                    TaskQueue.consumer_id == consumer_id,
                    TaskQueue.claim_token == claim_token,
                )
                .first()
            )
            if task:
                current_retries = task.retry_count or 0
                cooldown_minutes = 5 * (3**current_retries)
                retry_after = (
                    datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)
                ).isoformat()

                task.status = "pending"
                task.consumer_id = None
                task.claim_token = None
                task.claimed_at = None
                task.job_id = ""
                task.error = error[:200]
                task.retry_count = current_retries + 1
                task.retry_after = retry_after
                db.commit()
                self.release()
                return True
            return False
        except Exception:
            db.rollback()
            return False

    def release_task_claim(
        self, task_id: int, consumer_id: str, error: str = "", claim_token: str = ""
    ):
        db = self._get_db()
        try:
            task = (
                db.query(TaskQueue)
                .filter(
                    TaskQueue.id == task_id,
                    TaskQueue.status == "claimed",
                    TaskQueue.consumer_id == consumer_id,
                    TaskQueue.claim_token == claim_token,
                )
                .first()
            )
            if task:
                task.status = "pending"
                task.consumer_id = None
                task.claim_token = None
                task.claimed_at = None
                task.job_id = ""
                task.error = error[:200]
                db.commit()
                self.release()
                return True
            return False
        except Exception:
            db.rollback()
            return False

    def mark_reply_variant(
        self, task_id: int, variant_id: str, consumer_id: str, claim_token: str
    ):
        db = self._get_db()
        try:
            task = (
                db.query(TaskQueue)
                .filter(
                    TaskQueue.id == task_id,
                    TaskQueue.status == "claimed",
                    TaskQueue.consumer_id == consumer_id,
                    TaskQueue.claim_token == claim_token,
                )
                .first()
            )
            if task:
                task.reply_variant_id = variant_id
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False
