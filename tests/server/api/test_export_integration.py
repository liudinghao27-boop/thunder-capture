"""End-to-end export API integration test with an in-memory SQLAlchemy DB."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.main import app
from server.auth import get_current_user
from server.models import Base, get_db
from server.models.user import User
from server.models.industry import Industry
from server.models.task import TaskQueue


from sqlalchemy.pool import StaticPool

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def db_session():
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

    task = TaskQueue(
        industry_slug="test-ind",
        platform="douyin",
        video_id="v1",
        comment_id="c1",
        text="测试评论",
        user_name="u1",
        status="pending",
        owner_user_id=FakeUser.id,
    )
    db.add(task)

    db.commit()
    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)


def test_export_integration_csv(db_session, monkeypatch):
    from server import models

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: FakeUser()

    # Redirect endpoint-local SessionLocal to the in-memory test DB.
    monkeypatch.setattr(models, "SessionLocal", TestingSessionLocal)

    try:
        client = TestClient(app)
        resp = client.post(
            "/api/leads/export",
            json={"industry_slug": "test-ind", "format": "csv"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "测试评论" in resp.text
    finally:
        app.dependency_overrides.clear()
