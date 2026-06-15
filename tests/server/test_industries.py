"""Industry API tests."""

import uuid

import pytest
from fastapi.testclient import TestClient

from server.auth import get_current_user
from server.main import app
from server.models import SessionLocal
from server.models.industry import Industry
from server.models.user import User


@pytest.fixture
def db():
    """Provide a clean DB session for a test."""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def user(db):
    """Create a test user in the test database and clean it up after the test."""
    unique = str(uuid.uuid4())
    u = User(username=f"test-user-{unique}", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.delete(u)
    db.commit()


@pytest.fixture
def client(user):
    """Return a TestClient with authentication overridden to the test user."""
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def sample_industry(db, user):
    """Create a sample industry owned by the test user and clean it up after the test."""
    unique = str(uuid.uuid4())
    ind = Industry(
        id=unique,
        user_id=user.id,
        name="测试项目",
        slug=f"test-normalize-{unique}",
    )
    db.add(ind)
    db.commit()
    db.refresh(ind)
    yield ind
    db.delete(ind)
    db.commit()


def test_create_industry_normalizes_list_fields(client):
    """POST /api/industries should normalize list fields at creation."""
    resp = client.post(
        "/api/industries",
        json={
            "name": "Create Normalize",
            "slug": f"create-normalize-{uuid.uuid4()}",
            "intent_keywords": ["  想买  ", "咨询", "咨询", ""],
            "noise_keywords": ["  666  ", ""],
            "target_users": [" 宝妈 ", "宝妈"],
            "categories": [" 咨询 ", " 咨询 ", "其他"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["intent_keywords"] == ["想买", "咨询"]
    assert data["noise_keywords"] == ["666"]
    assert data["target_users"] == ["宝妈"]
    assert data["categories"] == ["咨询", "其他"]


def test_update_industry_normalizes_list_fields(client, sample_industry):
    """PUT /api/industries/{id} should normalize list fields on update."""
    resp = client.put(
        f"/api/industries/{sample_industry.id}",
        json={
            "intent_keywords": ["  想买  ", "咨询", "咨询", ""],
            "noise_keywords": ["  666  ", ""],
            "target_users": [" 宝妈 ", "宝妈"],
            "categories": [" 咨询 ", " 咨询 ", "其他"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent_keywords"] == ["想买", "咨询"]
    assert data["noise_keywords"] == ["666"]
    assert data["target_users"] == ["宝妈"]
    assert data["categories"] == ["咨询", "其他"]
