"""Cross-tenant isolation tests for Industry slug uniqueness.

These tests verify the fix for the critical audit finding:
"Industry slug 未全局唯一，导致跨租户数据错乱".
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.auth import get_current_user
from server.main import app
from server.models import Base, get_db
from server.models.industry import Industry
from server.models.task import TargetBlogger, TaskQueue
from server.models.user import User


class UserA:
    id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class UserB:
    id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    for user_cls in (UserA, UserB):
        db.add(
            User(
                id=user_cls.id, username=f"tester-{user_cls.id[:8]}", password_hash="x"
            )
        )

    db.commit()
    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@contextmanager
def _client_context(db_session, user_cls):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    user = db_session.query(User).filter(User.id == user_cls.id).first()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    import server.models as models_module
    import server.services.task_stats as task_stats_module

    original_models_session_local = models_module.SessionLocal
    original_task_stats_session_local = task_stats_module.SessionLocal
    models_module.SessionLocal = lambda: db_session
    task_stats_module.SessionLocal = lambda: db_session

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        models_module.SessionLocal = original_models_session_local
        task_stats_module.SessionLocal = original_task_stats_session_local


@pytest.fixture
def client_a(db_session):
    with _client_context(db_session, UserA) as client:
        yield client


@pytest.fixture
def client_b(db_session):
    with _client_context(db_session, UserB) as client:
        yield client


def _create_industry(client, slug):
    resp = client.post(
        "/api/industries",
        json={
            "name": "Cross-tenant Test",
            "slug": slug,
            "keywords": ["test"],
            "platforms": ["douyin"],
        },
    )
    return resp


def test_same_slug_for_same_user_is_rejected(db_session):
    """A slug may be reused across tenants; (user_id, slug) must be unique per user."""
    slug = "shared-slug"
    with _client_context(db_session, UserA) as client_a:
        resp_a = _create_industry(client_a, slug)
        assert resp_a.status_code == 201

        resp_dup = _create_industry(client_a, slug)
        assert resp_dup.status_code == 400
        assert "already exists" in resp_dup.json()["detail"].lower()

    with _client_context(db_session, UserB) as client_b:
        resp_b = _create_industry(client_b, slug)
        assert resp_b.status_code == 201


def test_delete_industry_does_not_touch_other_tenant_data(db_session, client_a):
    """Deleting UserA's industry must not delete UserB's TaskQueue/TargetBlogger rows."""
    slug = "cleanup-test"
    ind_a = Industry(
        id="ind-a",
        user_id=UserA.id,
        name="A",
        slug=slug,
        keywords=["a"],
        platforms=["douyin"],
    )
    ind_b = Industry(
        id="ind-b",
        user_id=UserB.id,
        name="B",
        slug=slug,
        keywords=["b"],
        platforms=["douyin"],
    )
    db_session.add_all([ind_a, ind_b])
    db_session.commit()

    now = datetime.now(timezone.utc).isoformat()
    db_session.add_all(
        [
            TaskQueue(
                industry_slug=slug,
                owner_user_id=UserA.id,
                video_id="va",
                comment_id="ca",
                text="A lead",
                status="pending",
                fetched_at=now,
            ),
            TaskQueue(
                industry_slug=slug,
                owner_user_id=UserB.id,
                video_id="vb",
                comment_id="cb",
                text="B lead",
                status="pending",
                fetched_at=now,
            ),
            TargetBlogger(
                sec_uid="sec-a",
                industry_slug=slug,
                owner_user_id=UserA.id,
                nickname="A blogger",
                discovered_at=now,
            ),
            TargetBlogger(
                sec_uid="sec-b",
                industry_slug=slug,
                owner_user_id=UserB.id,
                nickname="B blogger",
                discovered_at=now,
            ),
        ]
    )
    db_session.commit()

    resp = client_a.delete(f"/api/industries/{ind_a.id}")
    assert resp.status_code == 200

    remaining_tasks = {
        t.owner_user_id: t.text for t in db_session.query(TaskQueue).all()
    }
    assert UserA.id not in remaining_tasks
    assert remaining_tasks.get(UserB.id) == "B lead"

    remaining_bloggers = {
        b.owner_user_id: b.nickname for b in db_session.query(TargetBlogger).all()
    }
    assert UserA.id not in remaining_bloggers
    assert remaining_bloggers.get(UserB.id) == "B blogger"


def test_celery_send_dm_task_uses_user_id_to_resolve_industry(db_session):
    """When two tenants share a slug, send_dm_task must use user_id to find the right industry."""
    from adapters.celery.send import send_dm_task

    ind_a = Industry(
        id="ind-a",
        user_id=UserA.id,
        name="A",
        slug="shared",
        keywords=["a"],
        platforms=["douyin"],
    )
    ind_b = Industry(
        id="ind-b",
        user_id=UserB.id,
        name="B",
        slug="shared",
        keywords=["b"],
        platforms=["douyin"],
    )
    db_session.add_all([ind_a, ind_b])
    db_session.commit()

    worker_summary = {"device_id": "d1", "sent": 1, "failed": 0, "status": "done"}
    worker_mock = MagicMock()
    worker_mock.return_value.run.return_value = worker_summary

    import server.models as models_module

    original_session_local = models_module.SessionLocal
    models_module.SessionLocal = lambda: db_session
    try:
        with patch("core.task.worker.DeviceWorker", worker_mock):
            # Without user_id the task must not accidentally resolve UserB's industry.
            result = send_dm_task.run(
                device_id="d1",
                adb_serial="serial1",
                industry_slug="shared",
                user_id=UserA.id,
                task_data={"source_sec_uid": "sec1"},
                reply_msg="hello",
            )
    finally:
        models_module.SessionLocal = original_session_local

    assert result == worker_summary
    cfg = worker_mock.call_args.kwargs["industry"]
    assert cfg.user_id == UserA.id


def test_queue_stats_filters_by_owner_user_id(db_session, monkeypatch):
    """queue_stats must only aggregate rows owned by the requested user."""
    from server.services import task_stats as task_stats_module

    monkeypatch.setattr(task_stats_module, "SessionLocal", lambda: db_session)

    from server.services.task_stats import queue_stats

    now = datetime.now(timezone.utc).isoformat()
    db_session.add_all(
        [
            TaskQueue(
                industry_slug="shared",
                owner_user_id=UserA.id,
                video_id="v1",
                comment_id="c1",
                status="pending",
                fetched_at=now,
            ),
            TaskQueue(
                industry_slug="shared",
                owner_user_id=UserA.id,
                video_id="v2",
                comment_id="c2",
                status="done",
                fetched_at=now,
            ),
            TaskQueue(
                industry_slug="shared",
                owner_user_id=UserB.id,
                video_id="v3",
                comment_id="c3",
                status="done",
                fetched_at=now,
            ),
        ]
    )
    db_session.commit()

    stats = queue_stats("shared", owner_user_id=UserA.id)
    assert stats["total"] == 2
    assert stats["pending"] == 1
    assert stats["done"] == 1
