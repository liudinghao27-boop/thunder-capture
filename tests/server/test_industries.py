"""Industry API tests."""

import uuid

import pytest
from fastapi.testclient import TestClient

from server.auth import get_current_user
from server.main import app
from server.models import SessionLocal
from server.models.device import Device
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


def _make_ready_industry(db, ind):
    """Populate an industry so every content check passes."""
    ind.keywords = ["关键词"]
    ind.intent_keywords = ["想买"]
    ind.noise_keywords = ["666"]
    ind.categories = ["咨询"]
    ind.reply_tone = "教练"
    ind.reply_style = "亲切专业"
    db.commit()
    db.refresh(ind)


def test_industry_ready_state_complete(client, sample_industry, db, monkeypatch):
    """Ready-state should reflect all checks except missing device."""
    monkeypatch.setenv("THUNDER_DEEPSEEK_KEY", "test-key")
    _make_ready_industry(db, sample_industry)

    resp = client.get(f"/api/industries/{sample_industry.id}/ready-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["industry_id"] == sample_industry.id
    assert data["score"] == 87
    assert data["checks"]["has_api_key"] is True
    assert data["checks"]["has_device"] is False
    assert data["next_step"] == "请至少添加一台活跃设备以执行发送"


def test_industry_ready_state_no_api_key(client, sample_industry, db, monkeypatch):
    """Missing API key should be the highest-priority next step."""
    for key in ("THUNDER_DEEPSEEK_KEY", "THUNDER_ZHIPU_KEY", "THUNDER_OPENAI_KEY"):
        monkeypatch.delenv(key, raising=False)
    _make_ready_industry(db, sample_industry)
    device = Device(
        user_id=sample_industry.user_id,
        name="test-device",
        adb_serial="serial-1",
        is_active=True,
    )
    db.add(device)
    db.commit()

    resp = client.get(f"/api/industries/{sample_industry.id}/ready-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 87
    assert data["checks"]["has_api_key"] is False
    assert data["checks"]["has_device"] is True
    assert data["next_step"] == "请先配置 LLM API Key"


def test_industry_ready_state_compliance_missing_webhook(
    client, sample_industry, db, monkeypatch
):
    """Compliance mode without webhook should report the missing webhook."""
    monkeypatch.setenv("THUNDER_DEEPSEEK_KEY", "test-key")
    _make_ready_industry(db, sample_industry)
    sample_industry.compliance_mode = True
    sample_industry.webhook_url = ""
    device = Device(
        user_id=sample_industry.user_id,
        name="test-device",
        adb_serial="serial-2",
        is_active=True,
    )
    db.add(device)
    db.commit()

    resp = client.get(f"/api/industries/{sample_industry.id}/ready-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 87
    assert data["checks"]["compliance_ready"] is False
    assert data["next_step"] == "合规模式已开启，请配置 Webhook URL"


def test_industry_ready_state_with_device(client, sample_industry, db, monkeypatch):
    """All checks passing should yield a 100% ready state."""
    monkeypatch.setenv("THUNDER_DEEPSEEK_KEY", "test-key")
    _make_ready_industry(db, sample_industry)
    device = Device(
        user_id=sample_industry.user_id,
        name="test-device",
        adb_serial="serial-3",
        is_active=True,
    )
    db.add(device)
    db.commit()

    resp = client.get(f"/api/industries/{sample_industry.id}/ready-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 100
    assert data["ok"] is True
    assert all(data["checks"].values())
    assert data["next_step"] == "项目已就绪，可以开始采集"


def test_industry_ready_state_ok_reflects_score_threshold(
    client, sample_industry, db, monkeypatch
):
    """The ok field must be False when score < 75 and True when score >= 75."""
    for key in ("THUNDER_DEEPSEEK_KEY", "THUNDER_ZHIPU_KEY", "THUNDER_OPENAI_KEY"):
        monkeypatch.delenv(key, raising=False)

    resp = client.get(f"/api/industries/{sample_industry.id}/ready-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] < 75
    assert data["ok"] is False

    monkeypatch.setenv("THUNDER_DEEPSEEK_KEY", "test-key")
    _make_ready_industry(db, sample_industry)

    resp = client.get(f"/api/industries/{sample_industry.id}/ready-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] >= 75
    assert data["ok"] is True
