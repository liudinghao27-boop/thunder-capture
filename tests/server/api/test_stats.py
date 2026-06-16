from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.auth import get_current_user
from server.main import app
from server.models import Base, get_db
from server.models.industry import Industry
from server.models.task import TaskQueue
from server.models.user import User


client = TestClient(app)


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def db_session(monkeypatch):
    TEST_DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user = User(
        id=FakeUser.id,
        username="tester",
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
            text="t1",
            source_keyword="kw1",
            consumer_id="dev1",
            status="sent",
            fetched_at=now,
            owner_user_id=FakeUser.id,
        ),
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v2",
            comment_id="c2",
            text="t2",
            source_keyword="kw1",
            consumer_id="dev1",
            status="replied",
            fetched_at=now,
            owner_user_id=FakeUser.id,
        ),
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v3",
            comment_id="c3",
            text="t3",
            source_keyword="kw2",
            consumer_id="dev2",
            status="converted",
            fetched_at=now,
            owner_user_id=FakeUser.id,
        ),
    ]
    for row in rows:
        db.add(row)

    db.commit()
    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)


@contextmanager
def _stats_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_effect_stats_requires_auth():
    resp = client.get("/api/stats/effects?industry_slug=recruitment")
    assert resp.status_code in (401, 403)


def test_keyword_stats_requires_auth():
    resp = client.get("/api/stats/keywords?industry_slug=recruitment")
    assert resp.status_code in (401, 403)


def test_device_stats_requires_auth():
    resp = client.get("/api/stats/devices?industry_slug=recruitment")
    assert resp.status_code in (401, 403)


def test_keyword_stats_success(db_session):
    with _stats_client(db_session) as client:
        resp = client.get("/api/stats/keywords?industry_slug=test-ind")
        assert resp.status_code == 200
        data = resp.json()
        assert data["industry_slug"] == "test-ind"
        assert data["days"] == 7
        keywords = {item["keyword"]: item for item in data["keywords"]}
        assert "kw1" in keywords
        assert "kw2" in keywords
        assert keywords["kw1"]["collected"] == 2
        assert keywords["kw1"]["sent"] == 2
        assert keywords["kw1"]["replied"] == 1
        assert keywords["kw2"]["sent"] == 1
        assert keywords["kw2"]["converted"] == 1
        assert keywords["kw2"]["conversion_rate"] == 1.0


def test_device_stats_success(db_session):
    with _stats_client(db_session) as client:
        resp = client.get("/api/stats/devices?industry_slug=test-ind")
        assert resp.status_code == 200
        data = resp.json()
        assert data["industry_slug"] == "test-ind"
        assert data["days"] == 7
        devices = {item["device_id"]: item for item in data["devices"]}
        assert "dev1" in devices
        assert "dev2" in devices
        assert devices["dev1"]["sent"] == 2
        assert devices["dev1"]["replied"] == 1
        assert devices["dev2"]["sent"] == 1
        assert devices["dev2"]["converted"] == 1


def test_keyword_stats_rejects_invalid_days(db_session):
    with _stats_client(db_session) as client:
        resp = client.get("/api/stats/keywords?industry_slug=test-ind&days=0")
        assert resp.status_code == 422
        resp = client.get("/api/stats/keywords?industry_slug=test-ind&days=366")
        assert resp.status_code == 422
