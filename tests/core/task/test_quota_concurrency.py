from sqlalchemy.exc import IntegrityError

from core.task.scheduler import MatrixTaskScheduler
from server.models.task import IndustryDailyQuota


class _FakeDialect:
    name = "unknown"


class _FakeBind:
    dialect = _FakeDialect()


class _FakeQuery:
    def __init__(self, db):
        self._db = db

    def filter(self, *args):
        return self

    def first(self):
        self._db.query_count += 1
        if self._db.query_count == 1:
            return None
        return IndustryDailyQuota(
            industry_slug="ind", owner_user_id="u1", day="2026-07-03"
        )


class _FakeSession:
    def __init__(self):
        self.query_count = 0
        self.rollback_count = 0

    def get_bind(self):
        return _FakeBind()

    def query(self, model):
        assert model is IndustryDailyQuota
        return _FakeQuery(self)

    def add(self, obj):
        assert isinstance(obj, IndustryDailyQuota)
        raise IntegrityError("insert", {}, Exception("duplicate"))

    def flush(self):
        raise AssertionError("flush should not be reached after add failure")

    def rollback(self):
        self.rollback_count += 1


def test_unknown_dialect_quota_row_handles_integrity_race():
    scheduler = MatrixTaskScheduler(industry_slug="ind", global_daily_limit=1)
    db = _FakeSession()

    scheduler._ensure_quota_row(db, "2026-07-03")

    assert db.query_count == 2
    assert db.rollback_count == 1
