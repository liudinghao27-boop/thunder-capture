"""Tests for server/workers.py helpers."""

import time
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.models import Base
from server.models.industry import Industry
from server.models.user import User
from server.workers import _trigger_auto_export


TEST_DATABASE_URL = "sqlite:///:memory:"
_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture
def db_session(monkeypatch):
    Base.metadata.create_all(bind=_engine)
    db = TestingSessionLocal()
    monkeypatch.setattr("server.models.SessionLocal", TestingSessionLocal)
    yield db
    db.close()
    Base.metadata.drop_all(bind=_engine)


def _seed_industry(db_session, *, auto_export_enabled: bool, webhook_url: str):
    user = User(id="u1", username="tester", password_hash="x", is_active=True)
    industry = Industry(
        id="i1",
        user_id="u1",
        name="Test",
        slug="test-ind",
        keywords=["a"],
        platforms=["douyin"],
        categories=["c"],
        auto_export_enabled=auto_export_enabled,
        webhook_url=webhook_url,
    )
    db_session.add(user)
    db_session.add(industry)
    db_session.commit()


def test_trigger_auto_export_pushes_when_enabled(db_session):
    _seed_industry(
        db_session,
        auto_export_enabled=True,
        webhook_url="https://example.com/hook",
    )
    leads = [{"id": 1, "user_name": "u1", "text": "hello"}]

    with patch("server.services.webhook.push_leads_to_webhook") as mock_push:
        _trigger_auto_export("test-ind", "u1", leads)
        time.sleep(0.15)

    mock_push.assert_called_once()
    kwargs = mock_push.call_args.kwargs
    assert kwargs["webhook_url"] == "https://example.com/hook"
    assert kwargs["industry_slug"] == "test-ind"
    assert kwargs["industry_name"] == "Test"
    assert kwargs["leads"] == leads


def test_trigger_auto_export_skips_when_disabled(db_session):
    _seed_industry(
        db_session,
        auto_export_enabled=False,
        webhook_url="https://example.com/hook",
    )

    with patch("server.services.webhook.push_leads_to_webhook") as mock_push:
        _trigger_auto_export("test-ind", "u1", [{"id": 1}])

    mock_push.assert_not_called()


def test_trigger_auto_export_skips_when_no_webhook_url(db_session):
    _seed_industry(
        db_session,
        auto_export_enabled=True,
        webhook_url="",
    )

    with patch("server.services.webhook.push_leads_to_webhook") as mock_push:
        _trigger_auto_export("test-ind", "u1", [{"id": 1}])

    mock_push.assert_not_called()


def test_trigger_auto_export_limits_batch_to_500(db_session):
    _seed_industry(
        db_session,
        auto_export_enabled=True,
        webhook_url="https://example.com/hook",
    )
    leads = [{"id": i} for i in range(600)]

    with patch("server.services.webhook.push_leads_to_webhook") as mock_push:
        _trigger_auto_export("test-ind", "u1", leads)
        time.sleep(0.15)

    mock_push.assert_called_once()
    assert len(mock_push.call_args.kwargs["leads"]) == 500


def test_trigger_auto_export_swallows_errors(db_session):
    """Errors during the DB lookup or push must not propagate."""
    with patch("server.models.SessionLocal", side_effect=RuntimeError("boom")):
        _trigger_auto_export("test-ind", "u1", [{"id": 1}])
