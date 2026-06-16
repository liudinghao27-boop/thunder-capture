from unittest.mock import MagicMock
from core.task.scheduler import MatrixTaskScheduler


def _make_fake_db(quota=None, task=None):
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
            self.committed = 0
            self.rolled_back = 0
            self.flushed = 0

        def query(self, model):
            if model.__name__ == "IndustryDailyQuota":
                return FakeQuery(self.quota)
            return FakeQuery(self.task)

        def commit(self):
            self.committed += 1

        def rollback(self):
            self.rolled_back += 1

        def flush(self):
            self.flushed += 1

        def close(self):
            pass

    return FakeDb


def test_claim_respects_industry_daily_max(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=0, daily_send_max=1
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(quota={"sent": 1, "reserved": 0})
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    result = scheduler.claim_for_device("d1")
    assert result.task is None
    assert result.reason == "industry_daily_limit_reached"


def test_claim_reserves_daily_send_max_slot(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=0, daily_send_max=2
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(quota={"sent": 1, "reserved": 0}, task={
        "id": 1, "video_id": "v1", "comment_id": "c1", "text": "hi",
        "user_name": "u", "user_id": "uid", "short_id": "sid",
        "douyin_id": "did", "unique_id": "", "claim_token": "",
        "status": "pending"
    })
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    result = scheduler.claim_for_device("d1")
    db = scheduler._get_db()
    assert result.ok is True
    assert result.task is not None
    assert db.quota.reserved == 1


def test_mark_task_done_commits_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=10, daily_send_max=0
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(quota={"sent": 0, "reserved": 1}, task={
        "id": 1, "status": "claimed", "consumer_id": "d1", "claim_token": "t1"
    })
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.commit = MagicMock()
    scheduler.mark_task_done(1, "d1", ai_reply="ok", claim_token="t1")
    scheduler.commit.assert_called_once()


def test_mark_task_failed_releases_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=10, daily_send_max=0
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(quota={"sent": 0, "reserved": 1}, task={
        "id": 1, "status": "claimed", "consumer_id": "d1", "claim_token": "t1"
    })
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.release = MagicMock()
    scheduler.mark_task_failed(1, "d1", error="boom", claim_token="t1")
    scheduler.release.assert_called_once()


def test_mark_task_retry_releases_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=10, daily_send_max=0
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(quota={"sent": 0, "reserved": 1}, task={
        "id": 1, "status": "claimed", "consumer_id": "d1", "claim_token": "t1",
        "retry_count": 0
    })
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.release = MagicMock()
    scheduler.mark_task_retry(1, "d1", error="retry", claim_token="t1")
    scheduler.release.assert_called_once()


def test_release_task_claim_releases_quota_reservation(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=10, daily_send_max=0
    )
    import core.task.scheduler as sched_module

    FakeDb = _make_fake_db(quota={"sent": 0, "reserved": 1}, task={
        "id": 1, "status": "claimed", "consumer_id": "d1", "claim_token": "t1"
    })
    monkeypatch.setattr(sched_module, "SessionLocal", FakeDb)

    scheduler.release = MagicMock()
    scheduler.release_task_claim(1, "d1", error="released", claim_token="t1")
    scheduler.release.assert_called_once()
