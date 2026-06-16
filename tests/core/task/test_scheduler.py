from unittest.mock import MagicMock
from core.task.scheduler import MatrixTaskScheduler


def test_claim_respects_industry_daily_max(monkeypatch):
    scheduler = MatrixTaskScheduler(
        industry_slug="test", owner_user_id="u1", global_daily_limit=0, daily_send_max=1
    )
    import core.task.scheduler as sched_module

    class FakeQuota:
        sent = 1
        reserved = 0

    class FakeQuery:
        def filter(self, *a, **k): return self
        def with_for_update(self): return self
        def first(self): return FakeQuota()

    class FakeDb:
        def query(self, model): return FakeQuery()
        def commit(self): pass
        def rollback(self): pass
        def flush(self): pass
        def close(self): pass

    monkeypatch.setattr(sched_module, "SessionLocal", lambda: FakeDb())

    result = scheduler.claim_for_device("d1")
    assert result.task is None
    assert result.reason == "industry_daily_limit_reached"
