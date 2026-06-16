"""Dashboard routes tests."""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.auth import get_current_user
from server.main import app
from server.models import Base, get_db
from server.models.industry import Industry
from server.models.task import TaskQueue
from server.models.user import User


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


class OtherFakeUser:
    id = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def db_session():
    TEST_DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    for uid in (FakeUser.id, OtherFakeUser.id):
        user = User(
            id=uid,
            username=f"tester-{uid[:8]}",
            password_hash="x",
            is_active=True,
        )
        db.add(user)

    industry = Industry(
        id="ind-1",
        user_id=FakeUser.id,
        name="测试",
        slug="test-ind",
        keywords=["a"],
        platforms=["douyin"],
        categories=["c"],
    )
    db.add(industry)

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v1",
            comment_id="c1",
            text="owner done",
            status="done",
            fetched_at=now,
            owner_user_id=FakeUser.id,
        ),
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v2",
            comment_id="c2",
            text="owner failed",
            status="failed",
            error="blocked",
            fetched_at=now,
            owner_user_id=FakeUser.id,
        ),
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v3",
            comment_id="c3",
            text="other failed",
            status="failed",
            error="other-error",
            fetched_at=now,
            owner_user_id=OtherFakeUser.id,
        ),
    ]
    for row in rows:
        db.add(row)

    db.commit()
    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)


@contextmanager
def _client(db_session, user_cls=FakeUser):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def make_session():
        return db_session

    import server.models as models_module
    import server.services.task_stats as task_stats_module

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = user_cls
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(models_module, "SessionLocal", make_session)
    monkeypatch.setattr(task_stats_module, "SessionLocal", make_session)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        monkeypatch.undo()


def test_funnel_analytics_failure_distribution_filters_by_owner(db_session):
    with _client(db_session, FakeUser) as client:
        resp = client.get("/api/dashboard/funnel?industry_slug=test-ind")
    assert resp.status_code == 200
    data = resp.json()
    failure_dist = data["failure_distribution"]
    reasons = {item["reason"] for item in failure_dist}
    assert "blocked" in reasons
    assert "other-error" not in reasons
