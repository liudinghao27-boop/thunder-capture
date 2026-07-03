"""Cross-tenant isolation and lead status transition tests."""

from datetime import datetime, timezone
from contextlib import contextmanager

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
        # Owned by FakeUser
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v1",
            comment_id="c1",
            text="owner row",
            status="done",
            fetched_at=now,
            owner_user_id=FakeUser.id,
        ),
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v2",
            comment_id="c2",
            text="owner failed row",
            status="failed",
            fetched_at=now,
            owner_user_id=FakeUser.id,
        ),
        # Owned by other user
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v3",
            comment_id="c3",
            text="other row",
            status="failed",
            fetched_at=now,
            owner_user_id=OtherFakeUser.id,
        ),
        # Owner-agnostic row (empty owner)
        TaskQueue(
            industry_slug="test-ind",
            platform="douyin",
            video_id="v4",
            comment_id="c4",
            text="public row",
            status="done",
            fetched_at=now,
            owner_user_id="",
        ),
    ]
    for row in rows:
        db.add(row)

    db.commit()
    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


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
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        monkeypatch.undo()


def test_list_leads_filters_by_owner(db_session):
    with _client(db_session, FakeUser) as client:
        resp = client.get("/api/leads")
    assert resp.status_code == 200
    data = resp.json()
    texts = {lead["text"] for lead in data["leads"]}
    assert "owner row" in texts
    assert "owner failed row" in texts
    assert "public row" in texts
    assert "other row" not in texts
    assert data["total"] == 3


def test_lead_stats_filters_by_owner(db_session):
    with _client(db_session, FakeUser) as client:
        resp = client.get("/api/leads/stats?industry_slug=test-ind")
    assert resp.status_code == 200
    data = resp.json()
    # done includes the owned done row and the unowned (public) done row
    assert data["done"] == 2
    assert data["failed"] == 1
    assert data["total"] == 3


def test_retry_failed_leads_filters_by_owner(db_session):
    with _client(db_session, FakeUser) as client:
        resp = client.post("/api/leads/retry-failed?industry_slug=test-ind")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["code"] == "LEADS_REQUEUED"
    assert data["requeued"] == 1
    assert data["retried"] == 1
    assert data["skipped"] == 0

    db_session.expire_all()
    statuses = {
        row.status
        for row in db_session.query(TaskQueue).filter(TaskQueue.owner_user_id == FakeUser.id).all()
    }
    assert "failed" not in statuses


def test_retry_failed_leads_does_not_touch_other_owner(db_session):
    with _client(db_session, FakeUser) as client:
        resp = client.post("/api/leads/retry-failed?industry_slug=test-ind")
    assert resp.status_code == 200
    db_session.expire_all()
    other = db_session.query(TaskQueue).filter(
        TaskQueue.owner_user_id == OtherFakeUser.id
    ).first()
    assert other.status == "failed"


def test_mark_replied_accepts_done_status(db_session):
    lead = db_session.query(TaskQueue).filter(TaskQueue.comment_id == "c1").first()
    with _client(db_session, FakeUser) as client:
        resp = client.post(f"/api/leads/{lead.id}/mark-replied", json={"reply_text": "hi"})
    assert resp.status_code == 200


def test_mark_replied_rejects_pending_status(db_session):
    now = datetime.now(timezone.utc).isoformat()
    lead = TaskQueue(
        industry_slug="test-ind",
        platform="douyin",
        video_id="v5",
        comment_id="c5",
        text="pending",
        status="pending",
        fetched_at=now,
        owner_user_id=FakeUser.id,
    )
    db_session.add(lead)
    db_session.commit()
    with _client(db_session, FakeUser) as client:
        resp = client.post(f"/api/leads/{lead.id}/mark-replied", json={"reply_text": "hi"})
    assert resp.status_code == 400


def test_unmark_converted_fallback_to_done(db_session):
    now = datetime.now(timezone.utc).isoformat()
    lead = TaskQueue(
        industry_slug="test-ind",
        platform="douyin",
        video_id="v6",
        comment_id="c6",
        text="converted no reply",
        status="converted",
        fetched_at=now,
        owner_user_id=FakeUser.id,
    )
    db_session.add(lead)
    db_session.commit()
    with _client(db_session, FakeUser) as client:
        resp = client.post(f"/api/leads/{lead.id}/unmark-converted")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"


def test_unmark_converted_fallback_to_replied(db_session):
    now = datetime.now(timezone.utc).isoformat()
    lead = TaskQueue(
        industry_slug="test-ind",
        platform="douyin",
        video_id="v7",
        comment_id="c7",
        text="converted with reply",
        status="converted",
        replied_at=datetime.now(timezone.utc),
        fetched_at=now,
        owner_user_id=FakeUser.id,
    )
    db_session.add(lead)
    db_session.commit()
    with _client(db_session, FakeUser) as client:
        resp = client.post(f"/api/leads/{lead.id}/unmark-converted")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "replied"
