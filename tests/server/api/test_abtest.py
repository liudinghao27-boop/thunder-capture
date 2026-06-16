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
    db.commit()

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)


@contextmanager
def _auth_client(db_session):
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


def test_add_variant_requires_auth():
    resp = client.post("/api/industries/ind-1/variants", json={"name": "测试", "weight": 1})
    assert resp.status_code in (401, 403)


def test_list_variants_requires_auth():
    resp = client.get("/api/industries/ind-1/variants")
    assert resp.status_code in (401, 403)


def test_abtest_results_requires_auth():
    resp = client.get("/api/industries/ind-1/abtest-results")
    assert resp.status_code in (401, 403)


def test_add_variant_success(db_session):
    with _auth_client(db_session) as client:
        resp = client.post("/api/industries/ind-1/variants", json={"name": "测试变体", "weight": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reply_variants"]) == 1
        variant = data["reply_variants"][0]
        assert variant["name"] == "测试变体"
        assert variant["weight"] == 2
        assert variant.get("id")
        assert variant.get("enabled") is True


def test_add_variant_rejects_empty_name(db_session):
    with _auth_client(db_session) as client:
        resp = client.post("/api/industries/ind-1/variants", json={"name": "  ", "weight": 1})
        assert resp.status_code == 422


def test_add_variant_rejects_negative_weight(db_session):
    with _auth_client(db_session) as client:
        resp = client.post("/api/industries/ind-1/variants", json={"name": "测试", "weight": -1})
        assert resp.status_code == 422


def test_list_variants_success(db_session):
    with _auth_client(db_session) as client:
        client.post("/api/industries/ind-1/variants", json={"name": "测试变体", "weight": 1})
        resp = client.get("/api/industries/ind-1/variants")
        assert resp.status_code == 200
        data = resp.json()
        assert data["industry_id"] == "ind-1"
        assert len(data["variants"]) == 1
        assert data["variants"][0]["name"] == "测试变体"


def test_update_variant_success(db_session):
    with _auth_client(db_session) as client:
        add_resp = client.post("/api/industries/ind-1/variants", json={"name": "测试变体", "weight": 1})
        variant_id = add_resp.json()["reply_variants"][0]["id"]
        resp = client.put(f"/api/industries/ind-1/variants/{variant_id}", json={"weight": 5, "enabled": False})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reply_variants"]) == 1
        assert data["reply_variants"][0]["weight"] == 5
        assert data["reply_variants"][0]["enabled"] is False


def test_update_variant_not_found(db_session):
    with _auth_client(db_session) as client:
        resp = client.put("/api/industries/ind-1/variants/nonexistent", json={"weight": 5})
        assert resp.status_code == 404


def test_update_variant_rejects_empty_name(db_session):
    with _auth_client(db_session) as client:
        add_resp = client.post("/api/industries/ind-1/variants", json={"name": "测试变体", "weight": 1})
        variant_id = add_resp.json()["reply_variants"][0]["id"]
        resp = client.put(f"/api/industries/ind-1/variants/{variant_id}", json={"name": "  "})
        assert resp.status_code == 422


def test_update_variant_rejects_negative_weight(db_session):
    with _auth_client(db_session) as client:
        add_resp = client.post("/api/industries/ind-1/variants", json={"name": "测试变体", "weight": 1})
        variant_id = add_resp.json()["reply_variants"][0]["id"]
        resp = client.put(f"/api/industries/ind-1/variants/{variant_id}", json={"weight": -1})
        assert resp.status_code == 422


def test_delete_variant_success(db_session):
    with _auth_client(db_session) as client:
        add_resp = client.post("/api/industries/ind-1/variants", json={"name": "测试变体", "weight": 1})
        variant_id = add_resp.json()["reply_variants"][0]["id"]
        resp = client.delete(f"/api/industries/ind-1/variants/{variant_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_variants"] == []


def test_abtest_results_success(db_session):
    with _auth_client(db_session) as client:
        add_resp = client.post("/api/industries/ind-1/variants", json={"name": "赢家变体", "weight": 1})
        variant_id = add_resp.json()["reply_variants"][0]["id"]

        now = datetime.now(timezone.utc).isoformat()
        db_session.add(
            TaskQueue(
                industry_slug="test-ind",
                platform="douyin",
                video_id="v1",
                comment_id="c1",
                text="t1",
                status="replied",
                fetched_at=now,
                owner_user_id=FakeUser.id,
                reply_variant_id=variant_id,
            )
        )
        db_session.commit()

        resp = client.get("/api/industries/ind-1/abtest-results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["industry_id"] == "ind-1"
        assert len(data["variants"]) == 1
        variant_result = data["variants"][0]
        assert variant_result["id"] == variant_id
        assert variant_result["name"] == "赢家变体"
        assert variant_result["sent"] == 1
        assert variant_result["replied"] == 1
        assert variant_result["reply_rate"] == 1.0
        assert data["winner"] == variant_id


def test_abtest_results_rejects_invalid_days(db_session):
    with _auth_client(db_session) as client:
        resp = client.get("/api/industries/ind-1/abtest-results?days=0")
        assert resp.status_code == 422
        resp = client.get("/api/industries/ind-1/abtest-results?days=366")
        assert resp.status_code == 422
