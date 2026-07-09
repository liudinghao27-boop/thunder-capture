from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.task.scheduler import MatrixTaskScheduler
from server.models import Base
from server.models.task import ConsumerState, IndustryDailyQuota, TaskQueue


@pytest.fixture
def scheduler_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'scheduler.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    local_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("core.task.scheduler.SessionLocal", local_session)
    yield local_session
    engine.dispose()


def _make_fake_db(quota=None, task=None, consumer_state=None):
    class FakeQuota:
        def __init__(self, sent=0, reserved=0):
            self.sent = sent
            self.reserved = reserved

    class FakeTask:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class FakeQuery:
        def __init__(self, first_value=None):
            self._first = first_value

        def filter(self, *a, **k):
            return self

        def with_for_update(self, **kwargs):
            return self

        def order_by(self, *a):
            return self

        def first(self):
            return self._first

    class FakeDb:
        def __init__(self):
            self.quota = FakeQuota(**quota) if quota else None
            self.task = FakeTask(**task) if task else None
            self.consumer_state = FakeTask(**consumer_state) if consumer_state else None
            self.committed = 0
            self.rolled_back = 0
            self.flushed = 0

        def query(self, model):
            if model.__name__ == "IndustryDailyQuota":
                return FakeQuery(self.quota)
            if model.__name__ == "ConsumerState":
                return FakeQuery(self.consumer_state)
            return FakeQuery(self.task)

        def add(self, obj):
            if obj.__class__.__name__ == "ConsumerState":
                self.consumer_state = obj

        def commit(self):
            self.committed += 1

        def rollback(self):
            self.rolled_back += 1

        def flush(self):
            self.flushed += 1

        def close(self):
            pass

    return FakeDb


def test_claim_respects_industry_daily_max(scheduler_db):
    db = scheduler_db()
    db.add(
        IndustryDailyQuota(
            industry_slug="test",
            owner_user_id="u1",
            day=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            sent=1,
            reserved=0,
        )
    )
    db.commit()
    db.close()
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=0, daily_send_max=1
    )
    try:
        result = scheduler.claim_for_device("d1")
        assert result.task is None
        assert result.reason == "industry_daily_limit_reached"
    finally:
        scheduler.close()


def test_claim_reserves_daily_send_max_slot(scheduler_db):
    db = scheduler_db()
    db.add(
        IndustryDailyQuota(
            industry_slug="test",
            owner_user_id="u1",
            day=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            sent=1,
            reserved=0,
        )
    )
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v1",
            comment_id="c1",
            text="hi",
            user_name="u",
            user_id="uid",
            short_id="sid",
            status="pending",
        )
    )
    db.commit()
    db.close()
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=0, daily_send_max=2
    )
    try:
        result = scheduler.claim_for_device("d1")
        assert result.ok is True
        assert result.task is not None
    finally:
        scheduler.close()
    db = scheduler_db()
    try:
        quota = db.query(IndustryDailyQuota).filter_by(industry_slug="test").one()
        assert quota.reserved == 1
    finally:
        db.close()


def test_claim_skips_pending_task_until_retry_after_expires(scheduler_db):
    future_retry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    db = scheduler_db()
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v1",
            comment_id="c1",
            text="cooling down",
            user_name="u",
            user_id="uid",
            status="pending",
            retry_after=future_retry,
        )
    )
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v2",
            comment_id="c2",
            text="ready",
            user_name="u2",
            user_id="uid2",
            status="pending",
        )
    )
    db.commit()
    db.close()

    scheduler = MatrixTaskScheduler(industry_slug="test", owner_user_id="u1")
    try:
        result = scheduler.claim_for_device("d1")
        assert result.ok is True
        assert result.task["comment_id"] == "c2"
    finally:
        scheduler.close()


def test_claim_handles_retry_after_z_suffix_as_datetime(scheduler_db):
    future_retry = (
        (datetime.now(timezone.utc) + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z")
    )
    db = scheduler_db()
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v1",
            comment_id="c1",
            text="z cooling down",
            user_name="u",
            user_id="uid",
            status="pending",
            retry_after=future_retry,
        )
    )
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v2",
            comment_id="c2",
            text="ready",
            user_name="u2",
            user_id="uid2",
            status="pending",
        )
    )
    db.commit()
    db.close()

    scheduler = MatrixTaskScheduler(industry_slug="test", owner_user_id="u1")
    try:
        result = scheduler.claim_for_device("d1")
        assert result.ok is True
        assert result.task["comment_id"] == "c2"
    finally:
        scheduler.close()


def test_claim_respects_device_daily_limit(scheduler_db):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = scheduler_db()
    db.add(
        ConsumerState(
            consumer_id="d1",
            owner_user_id="u1",
            daily_sent=2,
            daily_limit=2,
            last_sent_date=today,
        )
    )
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v1",
            comment_id="c1",
            text="ready",
            user_name="u",
            user_id="uid",
            status="pending",
        )
    )
    db.commit()
    db.close()

    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        device_daily_limit=2,
    )
    try:
        result = scheduler.claim_for_device("d1")
        assert result.task is None
        assert result.reason == "device_daily_limit_reached"
    finally:
        scheduler.close()

    db = scheduler_db()
    try:
        task = db.query(TaskQueue).filter_by(comment_id="c1").one()
        assert task.status == "pending"
    finally:
        db.close()


def test_mark_task_done_increments_device_daily_sent(scheduler_db):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db = scheduler_db()
    task = TaskQueue(
        industry_slug="test",
        owner_user_id="u1",
        video_id="v1",
        comment_id="c1",
        text="ready",
        user_name="u",
        user_id="uid",
        status="claimed",
        consumer_id="d1",
        claim_token="token-1",
    )
    db.add(task)
    db.add(
        ConsumerState(
            consumer_id="d1",
            owner_user_id="u1",
            daily_sent=1,
            daily_limit=3,
            last_sent_date=today,
            total_sent=4,
        )
    )
    db.commit()
    task_id = task.id
    db.close()

    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        device_daily_limit=3,
    )
    try:
        assert (
            scheduler.mark_task_done(
                task_id, "d1", ai_reply="ok", claim_token="token-1"
            )
            is True
        )
    finally:
        scheduler.close()

    db = scheduler_db()
    try:
        state = db.query(ConsumerState).filter_by(consumer_id="d1").one()
        assert state.daily_sent == 2
        assert state.total_sent == 5
        assert state.last_sent_date == today
    finally:
        db.close()


def test_claim_respects_device_hourly_limit(scheduler_db):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    db = scheduler_db()
    db.add(
        ConsumerState(
            consumer_id="d1",
            owner_user_id="u1",
            daily_sent=2,
            daily_limit=10,
            last_sent_date=today,
            wave_sent=2,
            rate_limited_at=now.isoformat(),
        )
    )
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v1",
            comment_id="c1",
            text="ready",
            user_name="u",
            user_id="uid",
            status="pending",
        )
    )
    db.commit()
    db.close()

    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        hourly_send_limit=2,
    )
    try:
        result = scheduler.claim_for_device("d1")
        assert result.task is None
        assert result.reason == "device_hourly_limit_reached"
    finally:
        scheduler.close()


def test_claim_resets_expired_device_hourly_window(scheduler_db):
    old_window = datetime.now(timezone.utc) - timedelta(hours=2)
    db = scheduler_db()
    db.add(
        ConsumerState(
            consumer_id="d1",
            owner_user_id="u1",
            daily_sent=2,
            daily_limit=10,
            last_sent_date=old_window.strftime("%Y-%m-%d"),
            wave_sent=2,
            rate_limited_at=old_window.isoformat(),
        )
    )
    db.add(
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            video_id="v1",
            comment_id="c1",
            text="ready",
            user_name="u",
            user_id="uid",
            status="pending",
        )
    )
    db.commit()
    db.close()

    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        hourly_send_limit=2,
    )
    try:
        result = scheduler.claim_for_device("d1")
        assert result.ok is True
        assert result.task["comment_id"] == "c1"
    finally:
        scheduler.close()

    db = scheduler_db()
    try:
        state = db.query(ConsumerState).filter_by(consumer_id="d1").one()
        assert state.wave_sent == 0
        assert state.rate_limited_at == ""
    finally:
        db.close()


def test_mark_task_done_increments_device_hourly_window(scheduler_db):
    db = scheduler_db()
    task = TaskQueue(
        industry_slug="test",
        owner_user_id="u1",
        video_id="v1",
        comment_id="c1",
        text="ready",
        user_name="u",
        user_id="uid",
        status="claimed",
        consumer_id="d1",
        claim_token="token-1",
    )
    db.add(task)
    db.add(
        ConsumerState(
            consumer_id="d1",
            owner_user_id="u1",
            daily_sent=0,
            daily_limit=10,
            wave_sent=1,
            rate_limited_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    db.commit()
    task_id = task.id
    db.close()

    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        hourly_send_limit=2,
    )
    try:
        assert (
            scheduler.mark_task_done(
                task_id, "d1", ai_reply="ok", claim_token="token-1"
            )
            is True
        )
    finally:
        scheduler.close()

    db = scheduler_db()
    try:
        state = db.query(ConsumerState).filter_by(consumer_id="d1").one()
        assert state.wave_sent == 2
        assert state.rate_limited_at
    finally:
        db.close()


def test_mark_task_done_commits_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        global_daily_limit=10,
        daily_send_max=0,
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(
        quota={"sent": 0, "reserved": 1},
        task={"id": 1, "status": "claimed", "consumer_id": "d1", "claim_token": "t1"},
    )
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.commit = MagicMock()
    scheduler.mark_task_done(1, "d1", ai_reply="ok", claim_token="t1")
    scheduler.commit.assert_called_once()


def test_mark_task_failed_releases_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        global_daily_limit=10,
        daily_send_max=0,
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(
        quota={"sent": 0, "reserved": 1},
        task={"id": 1, "status": "claimed", "consumer_id": "d1", "claim_token": "t1"},
    )
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.release = MagicMock()
    scheduler.mark_task_failed(1, "d1", error="boom", claim_token="t1")
    scheduler.release.assert_called_once()


def test_mark_task_retry_releases_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        global_daily_limit=10,
        daily_send_max=0,
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(
        quota={"sent": 0, "reserved": 1},
        task={
            "id": 1,
            "status": "claimed",
            "consumer_id": "d1",
            "claim_token": "t1",
            "retry_count": 0,
        },
    )
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.release = MagicMock()
    scheduler.mark_task_retry(1, "d1", error="retry", claim_token="t1")
    scheduler.release.assert_called_once()


def test_release_task_claim_releases_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test",
        owner_user_id="u1",
        global_daily_limit=10,
        daily_send_max=0,
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(
        quota={"sent": 0, "reserved": 1},
        task={"id": 1, "status": "claimed", "consumer_id": "d1", "claim_token": "t1"},
    )
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.release = MagicMock()
    scheduler.release_task_claim(1, "d1", error="released", claim_token="t1")
    scheduler.release.assert_called_once()
