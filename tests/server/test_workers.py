"""Tests for server/workers.py helpers."""

import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.models import Base
from server.models.industry import Industry
from server.models.user import User
from server.workers import (
    _jobs,
    _jobs_lock,
    _set_job,
    cancel_job,
    get_job_status,
    run_collect_job,
    _trigger_auto_export,
)
from core.config import IndustryConfig


TEST_DATABASE_URL = "sqlite:///:memory:"
_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture
def db_session(monkeypatch):
    with _jobs_lock:
        _jobs.clear()
    Base.metadata.create_all(bind=_engine)
    db = TestingSessionLocal()
    monkeypatch.setattr("server.models.SessionLocal", TestingSessionLocal)
    yield db
    db.close()
    Base.metadata.drop_all(bind=_engine)
    with _jobs_lock:
        _jobs.clear()


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


def test_set_job_persists_state_to_database(db_session):
    """_set_job must write status/progress/phase into the Job table."""
    _set_job(
        "job-1",
        user_id="u1",
        type="collect",
        status="running",
        progress=42,
        phase="discover",
        industry_slug="test-ind",
        industry_name="Test",
    )

    from server.models.job import Job

    job = db_session.query(Job).filter(Job.id == "job-1").first()
    assert job is not None
    assert job.user_id == "u1"
    assert job.status == "running"
    assert job.progress == 42
    assert job.payload.get("phase") == "discover"
    assert job.industry_slug == "test-ind"
    assert job.industry_name == "Test"


def test_get_job_status_recovers_from_database(db_session):
    """If the in-memory cache is lost, get_job_status must still return the job."""
    _set_job(
        "job-2",
        user_id="u1",
        type="send",
        status="running",
        progress=33,
        phase="sending",
        industry_slug="test-ind",
        industry_name="Test",
    )

    # Simulate a process restart: drop the in-memory cache.
    with _jobs_lock:
        _jobs.pop("job-2", None)

    status = get_job_status("job-2", user_id="u1")
    assert status is not None
    assert status["status"] == "running"
    assert status["progress"] == 33
    assert status["phase"] == "sending"
    assert status["type"] == "send"


def test_get_job_status_enforces_ownership(db_session):
    """get_job_status must hide jobs that do not belong to the requesting user."""
    _set_job(
        "job-3",
        user_id="u1",
        type="collect",
        status="running",
        progress=0,
        industry_slug="test-ind",
    )
    assert get_job_status("job-3", user_id="u1") is not None
    assert get_job_status("job-3", user_id="u2") is None


def test_run_collect_job_persists_queue_funnel_summary(db_session):
    cfg = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["kw"],
        reply_tone="",
        reply_style="",
        categories=["咨询"],
        platforms=["douyin"],
        target_users=["target-a"],
        user_id="u1",
    )
    comments = [{
        "industry_slug": "test-ind",
        "text": "想咨询报名流程",
        "source_sec_uid": "sec-a",
        "source_short_id": "comment-1",
        "source_video_id": "video-1",
    }]

    async def fake_run_discovery(*args, **kwargs):
        return comments

    with patch("server.workers.run_discovery", fake_run_discovery), \
         patch("server.workers.classify_batch", return_value=comments), \
         patch("server.workers.enqueue_classified_result", return_value={
             "received": 1,
             "valid": 1,
             "inserted": 0,
             "duplicates": 1,
             "invalid": 0,
         }), \
         patch("server.workers.get_llm_client", return_value=object()):
        job_id = run_collect_job(cfg)
        time.sleep(0.2)

    status = get_job_status(job_id, user_id="u1")
    summary = status["collect_summary"]
    assert status["status"] == "done"
    assert summary["candidate_comments"] == 1
    assert summary["classified_passed"] == 1
    assert summary["enqueued"] == 0
    assert summary["queue_received"] == 1
    assert summary["queue_valid"] == 1
    assert summary["queue_duplicates"] == 1
    assert summary["queue_invalid"] == 0
    assert summary["target_user_count"] == 1
    assert summary["keyword_count"] == 1


def test_run_collect_job_persists_source_breakdown_summary(db_session):
    cfg = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["kw"],
        reply_tone="",
        reply_style="",
        categories=["鍜ㄨ"],
        platforms=["douyin"],
        target_users=["target-a"],
        user_id="u1",
    )
    comments = [
        {
            "industry_slug": "test-ind",
            "text": "keyword comment",
            "source_sec_uid": "sec-keyword",
            "source_short_id": "comment-keyword",
            "source_video_id": "video-keyword",
            "source_type": "keyword",
        },
        {
            "industry_slug": "test-ind",
            "text": "target comment",
            "source_sec_uid": "sec-target",
            "source_short_id": "comment-target",
            "source_video_id": "video-target",
            "source_type": "target_account",
        },
    ]

    async def fake_run_discovery(*args, **kwargs):
        return comments

    with patch("server.workers.run_discovery", fake_run_discovery), \
         patch("server.workers.classify_batch", return_value=comments), \
         patch("server.workers.enqueue_classified_result", return_value={
             "received": 2,
             "valid": 2,
             "inserted": 2,
             "duplicates": 0,
             "invalid": 0,
         }), \
         patch("server.workers.get_llm_client", return_value=object()):
        job_id = run_collect_job(cfg)
        time.sleep(0.2)

    status = get_job_status(job_id, user_id="u1")
    summary = status["collect_summary"]
    assert status["status"] == "done"
    assert summary["candidate_comments"] == 2
    assert summary["keyword_candidates"] == 1
    assert summary["target_candidates"] == 1
    assert summary["deduped_candidates"] == 2
    assert summary["source_breakdown"] == {"keyword": 1, "target_account": 1}
    assert summary["queue_received"] == 2
    assert summary["queue_valid"] == 2
    assert summary["queue_duplicates"] == 0
    assert summary["queue_invalid"] == 0


def test_run_collect_job_marks_empty_discovery_with_warning(db_session):
    cfg = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["kw"],
        reply_tone="",
        reply_style="",
        categories=["consult"],
        platforms=["douyin"],
        target_users=["target-a"],
        user_id="u1",
    )

    async def fake_run_discovery(*args, **kwargs):
        return []

    with patch("server.workers.run_discovery", fake_run_discovery), \
         patch("server.workers.get_llm_client", return_value=object()):
        job_id = run_collect_job(cfg)
        time.sleep(0.2)

    status = get_job_status(job_id, user_id="u1")
    summary = status["collect_summary"]
    assert status["status"] == "done"
    assert summary["candidate_comments"] == 0
    assert summary["enqueued"] == 0
    assert summary["empty_reason"] == "no_source_comments"
    assert "MediaCrawler" in summary["warning"]


def test_cancel_job_persists_cancel_request(db_session):
    """cancel_job must persist the cancellation flag and status."""
    _set_job(
        "job-4",
        user_id="u1",
        type="collect",
        status="running",
        progress=50,
        industry_slug="test-ind",
        industry_name="Test",
    )

    result = cancel_job("job-4", user_id="u1")
    assert result is not None
    assert result["status"] == "cancelling"
    assert result["cancel_requested"] is True

    from server.models.job import Job

    job = db_session.query(Job).filter(Job.id == "job-4").first()
    assert job.cancel_requested is True
    assert job.status == "cancelling"
    assert job.cancel_requested is True


def test_cancel_send_job_releases_claimed_task_and_quota_reservation(db_session):
    """Cancelling a send job must release both queue claim and quota reservation."""
    from server.models.task import IndustryDailyQuota, TaskQueue

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db_session.add(
        TaskQueue(
            industry_slug="test-ind",
            owner_user_id="u1",
            video_id="v1",
            comment_id="c1",
            text="hello",
            user_name="lead",
            user_id="lead-1",
            status="claimed",
            consumer_id="dev-1",
            claim_token="job-quota:claim-1",
            claimed_at=datetime.now(timezone.utc).isoformat(),
            job_id="job-quota",
        )
    )
    db_session.add(
        IndustryDailyQuota(
            industry_slug="test-ind",
            day=day,
            sent=0,
            reserved=1,
        )
    )
    db_session.commit()

    _set_job(
        "job-quota",
        user_id="u1",
        type="send",
        status="running",
        progress=50,
        industry_slug="test-ind",
        industry_name="Test",
    )

    result = cancel_job("job-quota", user_id="u1")

    task = db_session.query(TaskQueue).filter_by(comment_id="c1").one()
    quota = db_session.query(IndustryDailyQuota).filter_by(industry_slug="test-ind", day=day).one()
    assert result is not None
    assert result["released_claimed_tasks"] == 1
    assert task.status == "pending"
    assert task.consumer_id is None
    assert task.claim_token is None
    assert quota.reserved == 0


def test_run_senders_returns_cancelled_when_device_thread_does_not_exit(monkeypatch):
    """A stuck device worker must not keep the send job cancellation pending forever."""
    from core.task import worker as worker_module

    class DeviceStub:
        def as_sender_dict(self):
            return {
                "id": "dev-1",
                "adb_serial": "serial-1",
                "daily_limit": 10,
                "min_interval_sec": 1,
            }

    class BrokenCeleryApp:
        def connection(self):
            raise RuntimeError("broker unavailable")

    monkeypatch.setattr(worker_module, "load_active_devices", lambda **_kwargs: [DeviceStub()])
    monkeypatch.setattr(worker_module, "_SENDER_JOIN_POLL_SECONDS", 0.01)
    monkeypatch.setattr(worker_module, "_SENDER_CANCEL_GRACE_SECONDS", 0.03)
    monkeypatch.setattr("adapters.celery.app.app", BrokenCeleryApp())

    def stuck_device(*_args, **_kwargs):
        time.sleep(0.25)
        return {"device_id": "dev-1", "status": "done", "sent": 1, "failed": 0}

    monkeypatch.setattr(worker_module, "_run_device", stuck_device)
    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["k"],
        reply_tone="tone",
        reply_style="style",
        categories=["c"],
        user_id="u1",
        send_start_time="00:00",
        send_end_time="23:59",
    )

    started = time.monotonic()
    result = worker_module.run_senders(
        industry,
        should_stop=lambda: True,
        job_id="job-cancel-test",
    )

    assert time.monotonic() - started < 0.2
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["devices_total"] == 1
    assert result["devices"][0]["status"] == "cancelling_timeout"
