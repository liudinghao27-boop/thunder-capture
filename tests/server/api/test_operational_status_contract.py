from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.auth import get_current_user
from server.main import app
from server.models import Base, get_db
from server.models.job import Job
from server.models.user import User


TEST_USER_ID = "22222222-2222-2222-2222-222222222222"


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
    user = User(
        id=TEST_USER_ID,
        username="ops-user",
        password_hash="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@contextmanager
def _client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    user = db_session.query(User).filter(User.id == TEST_USER_ID).first()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_device_not_found_uses_standard_error(db_session):
    with _client(db_session) as client:
        res = client.post("/api/devices/not-exist/prepare-keyboard")

    assert res.status_code == 404
    assert res.json()["ok"] is False
    assert res.json()["code"] == "DEVICE_NOT_FOUND"
    assert res.json()["message"] == "Device not found"


def test_job_status_exposes_cancel_and_retry_contract(db_session):
    db_session.add(
        Job(
            id="job-ops-1",
            user_id=TEST_USER_ID,
            type="send",
            status="failed",
            progress=100,
            error="device offline",
            payload={},
        )
    )
    db_session.commit()

    with _client(db_session) as client:
        res = client.get("/api/jobs?limit=1")

    assert res.status_code == 200
    payload = res.json()
    assert payload
    row = payload[0]
    assert row["status"] == "failed"
    assert row["can_cancel"] is False
    assert row["can_retry"] is True
    assert row["failure_reason"] == "device offline"
    assert row["quota_released"] is True
