"""Auth routes tests."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.auth import get_current_user
from server.config import ALGORITHM, SECRET_KEY
from server.main import app
from server.models import Base, get_db
from server.models.user import User
from server.secret_store import decrypt_secret, encrypt_secret


TEST_USER_ID = "11111111-1111-1111-1111-111111111111"


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
        id=TEST_USER_ID,
        username="tester",
        password_hash="x",
        is_active=True,
        deepseek_key=encrypt_secret("original-key"),
        zhipu_key=encrypt_secret("zhipu-key"),
        openai_key="",
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


def test_get_settings_returns_masked_keys(db_session):
    with _client(db_session) as client:
        resp = client.get("/api/auth/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "****" in data["deepseek_key"]
    assert "****" in data["zhipu_key"]
    assert data["openai_key"] == ""
    # Verify underlying user row was not modified
    user = db_session.query(User).filter(User.id == TEST_USER_ID).first()
    assert decrypt_secret(user.deepseek_key) == "original-key"


def test_update_settings_none_leaves_key_unchanged(db_session):
    with _client(db_session) as client:
        resp = client.post("/api/auth/settings", json={"zhipu_key": None})
    assert resp.status_code == 200
    db_session.expire_all()
    user = db_session.query(User).filter(User.id == TEST_USER_ID).first()
    assert decrypt_secret(user.deepseek_key) == "original-key"
    assert decrypt_secret(user.zhipu_key) == "zhipu-key"


def test_update_settings_empty_string_clears_key(db_session):
    with _client(db_session) as client:
        resp = client.post("/api/auth/settings", json={"deepseek_key": ""})
    assert resp.status_code == 200
    db_session.expire_all()
    user = db_session.query(User).filter(User.id == TEST_USER_ID).first()
    assert user.deepseek_key == ""


def test_update_settings_non_empty_encrypts_key(db_session):
    with _client(db_session) as client:
        resp = client.post("/api/auth/settings", json={"deepseek_key": "new-secret-key"})
    assert resp.status_code == 200
    db_session.expire_all()
    user = db_session.query(User).filter(User.id == TEST_USER_ID).first()
    assert decrypt_secret(user.deepseek_key) == "new-secret-key"
    # Should not be the literal plaintext in DB
    assert user.deepseek_key != "new-secret-key"


def test_update_settings_ignores_masked_string(db_session):
    """Old '****' substring check is removed: any non-empty string is encrypted."""
    with _client(db_session) as client:
        resp = client.post("/api/auth/settings", json={"deepseek_key": "****masked"})
    assert resp.status_code == 200
    db_session.expire_all()
    user = db_session.query(User).filter(User.id == TEST_USER_ID).first()
    assert decrypt_secret(user.deepseek_key) == "****masked"


def test_auth_status_reports_registration_closed_when_users_exist(monkeypatch, db_session):
    monkeypatch.delenv("THUNDER_ALLOW_REGISTRATION", raising=False)
    with _client(db_session) as client:
        resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_users"] is True
    assert data["registration_open"] is False
    assert data["mode"] == "login_only"


def test_auth_status_reports_registration_open_when_explicitly_enabled(monkeypatch, db_session):
    monkeypatch.setenv("THUNDER_ALLOW_REGISTRATION", "1")
    with _client(db_session) as client:
        resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_users"] is True
    assert data["registration_open"] is True
    assert data["mode"] == "open"


def test_access_token_contains_standard_claims():
    from server.auth import create_access_token

    token = create_access_token(TEST_USER_ID)
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

    assert payload["sub"] == TEST_USER_ID
    assert "exp" in payload
    assert "iat" in payload
    assert "nbf" in payload
    assert "jti" in payload
