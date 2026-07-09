"""Tests for adapters/celery/send.py compliance check."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from adapters.celery.send import run_send_batch, send_dm_task
from server.models import Base
from server.models.industry import Industry
from server.models.user import User


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


def _seed_industry(db_session, *, compliance_mode: bool):
    user = User(id="u1", username="tester", password_hash="x", is_active=True)
    industry = Industry(
        id="i1",
        user_id="u1",
        name="Test",
        slug="test-ind",
        keywords=["a"],
        platforms=["douyin"],
        categories=["c"],
        compliance_mode=compliance_mode,
    )
    db_session.add(user)
    db_session.add(industry)
    db_session.commit()


def test_send_dm_task_skips_when_compliance_mode_enabled(db_session, monkeypatch):
    _seed_industry(db_session, compliance_mode=True)
    retry_mock = MagicMock()
    monkeypatch.setattr(send_dm_task, "retry", retry_mock)

    result = send_dm_task.run(
        device_id="d1",
        adb_serial="serial1",
        industry_slug="test-ind",
        user_id="u1",
        task_data={"source_sec_uid": "sec1"},
        reply_msg="hello",
    )

    assert result == {"ok": True, "skipped": True, "reason": "compliance_mode"}
    retry_mock.assert_not_called()


def test_send_dm_task_runs_when_compliance_mode_disabled(db_session, monkeypatch):
    _seed_industry(db_session, compliance_mode=False)
    retry_mock = MagicMock()
    monkeypatch.setattr(send_dm_task, "retry", retry_mock)

    worker_summary = {"device_id": "d1", "sent": 1, "failed": 0, "status": "done"}
    worker_mock = MagicMock()
    worker_mock.return_value.run.return_value = worker_summary
    monkeypatch.setattr("core.task.worker.DeviceWorker", worker_mock)

    result = send_dm_task.run(
        device_id="d1",
        adb_serial="serial1",
        industry_slug="test-ind",
        user_id="u1",
        task_data={"source_sec_uid": "sec1"},
        reply_msg="hello",
    )

    assert result == worker_summary
    worker_mock.assert_called_once()
    should_stop = worker_mock.call_args.kwargs["should_stop"]
    assert should_stop() is False
    retry_mock.assert_not_called()


def test_run_send_batch_requires_user_id(db_session, monkeypatch):
    _seed_industry(db_session, compliance_mode=False)
    with patch("core.task.worker.run_senders") as mock_run:
        mock_run.return_value = {"ok": True, "sent_total": 1}
        result = run_send_batch.run("test-ind", "")
        assert result["ok"] is False
        assert "user_id is required" in result["error"]


def test_run_send_batch_dispatches_for_user(db_session, monkeypatch):
    _seed_industry(db_session, compliance_mode=False)
    with patch("core.task.worker.run_senders") as mock_run:
        mock_run.return_value = {"ok": True, "sent_total": 1}
        result = run_send_batch.run("test-ind", "u1")
        assert result["ok"] is True
        assert mock_run.called


def test_send_dm_task_skips_when_industry_missing(db_session, monkeypatch):
    """If the industry row is missing, the task returns an error dict."""
    retry_mock = MagicMock()
    monkeypatch.setattr(send_dm_task, "retry", retry_mock)

    result = send_dm_task.run(
        device_id="d1",
        adb_serial="serial1",
        industry_slug="missing-ind",
        user_id="u1",
        task_data={"source_sec_uid": "sec1"},
        reply_msg="hello",
    )

    assert result == {"ok": False, "error": "Industry missing-ind not found"}
    retry_mock.assert_not_called()


def test_send_dm_task_has_no_global_rate_limit():
    """Global Celery rate_limit was removed; per-device limiting is handled by DeviceWorker."""
    assert send_dm_task.rate_limit is None
