import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.models import Base
from server.models.task import TaskQueue
from server.services.analytics import (
    aggregate_by_keyword,
    aggregate_by_device,
    query_task_rows,
)


TEST_DATABASE_URL = "sqlite:///:memory:"
_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=_engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=_engine)


def test_aggregate_by_keyword_empty():
    result = aggregate_by_keyword("test", [])
    assert result == []


def test_aggregate_by_keyword_groups():
    rows = [
        {"source_keyword": "当兵", "status": "sent"},
        {"source_keyword": "当兵", "status": "replied"},
        {"source_keyword": "征兵", "status": "converted"},
    ]
    result = aggregate_by_keyword("test", rows)
    assert len(result) == 2
    by_kw = {r["keyword"]: r for r in result}
    assert by_kw["当兵"]["sent"] == 2
    assert by_kw["当兵"]["replied"] == 1
    assert by_kw["征兵"]["converted"] == 1
    assert by_kw["征兵"]["conversion_rate"] == 1.0


def test_aggregate_by_device_groups():
    rows = [
        {"consumer_id": "d1", "status": "sent"},
        {"consumer_id": "d1", "status": "failed"},
        {"consumer_id": "d2", "status": "replied"},
    ]
    result = aggregate_by_device("test", rows)
    assert len(result) == 2
    by_dev = {r["device_id"]: r for r in result}
    assert by_dev["d1"]["sent"] == 1
    assert by_dev["d1"]["failed"] == 1
    assert by_dev["d2"]["replied"] == 1


def test_query_task_rows_filters_by_date_and_industry(db_session):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    rows = [
        TaskQueue(
            industry_slug="test",
            consumer_id="d1",
            fetched_at=now.isoformat(),
            status="sent",
            video_id="v1",
            comment_id="c1",
        ),
        TaskQueue(
            industry_slug="test",
            consumer_id="d2",
            fetched_at=old.isoformat(),
            status="replied",
            video_id="v2",
            comment_id="c2",
        ),
        TaskQueue(
            industry_slug="other",
            consumer_id="d3",
            fetched_at=now.isoformat(),
            status="sent",
            video_id="v3",
            comment_id="c3",
        ),
        TaskQueue(
            industry_slug="test",
            consumer_id="d4",
            fetched_at="",
            status="pending",
            video_id="v4",
            comment_id="c4",
        ),
    ]
    db_session.add_all(rows)
    db_session.commit()

    result = query_task_rows(db_session, "test", days=7)
    assert len(result) == 1
    assert result[0]["consumer_id"] == "d1"
    assert result[0]["status"] == "sent"


def test_query_task_rows_filters_by_owner_user_id(db_session):
    now = datetime.now(timezone.utc)
    rows = [
        TaskQueue(
            industry_slug="test",
            owner_user_id="u1",
            consumer_id="d1",
            fetched_at=now.isoformat(),
            status="sent",
            video_id="v1",
            comment_id="c1",
        ),
        TaskQueue(
            industry_slug="test",
            owner_user_id="u2",
            consumer_id="d2",
            fetched_at=now.isoformat(),
            status="replied",
            video_id="v2",
            comment_id="c2",
        ),
    ]
    db_session.add_all(rows)
    db_session.commit()

    result = query_task_rows(db_session, "test", days=7, owner_user_id="u1")
    assert len(result) == 1
    assert result[0]["consumer_id"] == "d1"
