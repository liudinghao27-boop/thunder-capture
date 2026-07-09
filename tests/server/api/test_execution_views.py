from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.auth import get_current_user
from server.main import app
from server.models import Base, get_db
from server.models.device import Device
from server.models.job import Job
from server.models.matrix import DeviceState, ExecutionLog, ScreenSnapshot
from server.models.user import User


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    db.add(
        User(
            id=FakeUser.id,
            username="tester",
            password_hash="x",
            is_active=True,
        )
    )
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

    def make_session():
        return db_session

    import server.models as models_module

    monkeypatch = pytest.MonkeyPatch()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    monkeypatch.setattr(models_module, "SessionLocal", make_session)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        monkeypatch.undo()


def test_jobs_view_normalizes_sent_status_and_exposes_latest_evidence(db_session):
    now = datetime.now(timezone.utc)
    db_session.add(
        Job(
            id="job-1",
            user_id=FakeUser.id,
            industry_slug="recruitment",
            industry_name="征兵咨询",
            type="send",
            status="done",
            progress=100,
            payload={
                "send_summary": {
                    "ok": True,
                    "sent_total": 1,
                    "failed_total": 0,
                    "devices": [{"device_id": "dev-1", "sent": 1, "failed": 0}],
                },
            },
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
    )
    db_session.add(
        ScreenSnapshot(
            id="snap-1",
            user_id=FakeUser.id,
            device_id="dev-1",
            job_id="job-1",
            screen_name="chat",
            image_path="data/acceptance/success.png",
            ocr_text="验收测试，请忽略",
            ui_tree={"blocker": "对方回复后才能发消息"},
            captured_at=now,
            created_at=now,
        )
    )
    db_session.add(
        ExecutionLog(
            id="log-1",
            user_id=FakeUser.id,
            job_id="job-1",
            device_id="dev-1",
            action="phone_agent_goal",
            status="done",
            detail="message sent",
            payload={
                "send_verification": {
                    "ok": True,
                    "reason": "message_visible",
                    "confidence": 0.88,
                    "screenshot_path": "data/acceptance/success.png",
                },
                "agent_decisions": {
                    "before": {
                        "page_state": "profile",
                        "confidence": 0.84,
                        "next_action": "open_chat",
                        "reason": "Profile page is visible.",
                        "screenshot": "data/acceptance/before.png",
                        "blocker": "",
                    },
                    "after": {
                        "page_state": "message_sent",
                        "confidence": 0.91,
                        "next_action": "confirm_success",
                        "reason": "Message send evidence is visible.",
                        "screenshot": "data/acceptance/success.png",
                        "blocker": "",
                    },
                },
            },
            created_at=now,
        )
    )
    db_session.commit()

    with _client(db_session) as client:
        list_resp = client.get("/api/jobs")
        detail_resp = client.get("/api/jobs/job-1")

    assert list_resp.status_code == 200
    assert detail_resp.status_code == 200

    job = list_resp.json()[0]
    detail = detail_resp.json()

    assert job["normalized_status"] == "sent"
    assert job["status_label"] == "已发送"
    assert "发送确认" in (job["final_reason"] or "")
    assert job["latest_execution"]["agent_decision"]["next_action"] == "confirm_success"
    assert detail["latest_execution"]["device_id"] == "dev-1"
    assert (
        detail["latest_execution"]["agent_decision"]["next_action"] == "confirm_success"
    )
    assert (
        detail["latest_execution"]["agent_decision"]["screenshot"]
        == "data/acceptance/success.png"
    )
    assert (
        detail["latest_execution"]["agent_decisions"]["before"]["next_action"]
        == "open_chat"
    )
    assert detail["latest_snapshot"]["image_path"] == "data/acceptance/success.png"
    assert detail["latest_snapshot"]["blocker"] == "对方回复后才能发消息"


def test_agent_logs_and_execution_monitor_expose_agent_decision(db_session):
    now = datetime.now(timezone.utc)
    decision = {
        "page_state": "blocked",
        "confidence": 0.98,
        "next_action": "stop",
        "reason": "Blocked by risk_control.",
        "screenshot": "data/evidence/risk.png",
        "blocker": "risk_control",
    }
    db_session.add(
        DeviceState(
            id="state-agent-1",
            user_id=FakeUser.id,
            device_id="dev-1",
            job_id="job-agent-1",
            status="error",
            current_app="com.ss.android.ugc.aweme",
            current_screen="blocked",
            health={"agent_decision": decision},
            last_heartbeat=now,
            updated_at=now,
        )
    )
    db_session.add(
        ScreenSnapshot(
            id="snap-agent-1",
            user_id=FakeUser.id,
            device_id="dev-1",
            job_id="job-agent-1",
            screen_name="blocked",
            blocker="risk_control",
            image_path="data/evidence/risk.png",
            ocr_text="Too many operations",
            ui_tree={"decision": decision},
            captured_at=now,
            created_at=now,
        )
    )
    db_session.add(
        ExecutionLog(
            id="log-agent-1",
            user_id=FakeUser.id,
            job_id="job-agent-1",
            device_id="dev-1",
            action="observe_screen",
            status="blocked",
            detail="before_execute: screen=blocked",
            payload={"decision": decision},
            created_at=now,
        )
    )
    db_session.commit()

    with _client(db_session) as client:
        logs_resp = client.get("/api/agent/execution-logs?job_id=job-agent-1")
        monitor_resp = client.get("/api/dashboard/execution?job_id=job-agent-1")

    assert logs_resp.status_code == 200
    assert monitor_resp.status_code == 200
    log = logs_resp.json()[0]
    assert log["agent_decision"]["next_action"] == "stop"
    assert log["agent_decision"]["blocker"] == "risk_control"
    device = monitor_resp.json()["devices"][0]
    assert device["agent_decision"]["next_action"] == "stop"
    assert device["decision_reason"] == "Blocked by risk_control."
    assert device["decision_screenshot"] == "data/evidence/risk.png"


def test_jobs_view_marks_unconfirmed_send_without_collapsing_into_generic_failure(
    db_session,
):
    now = datetime.now(timezone.utc)
    db_session.add(
        Job(
            id="job-2",
            user_id=FakeUser.id,
            industry_slug="recruitment",
            industry_name="征兵咨询",
            type="send",
            status="failed",
            progress=100,
            error="unconfirmed_send",
            payload={"send_summary": {"ok": False, "sent_total": 0, "failed_total": 1}},
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
    )
    db_session.add(
        ExecutionLog(
            id="log-2",
            user_id=FakeUser.id,
            job_id="job-2",
            device_id="dev-1",
            action="phone_agent_goal",
            status="unconfirmed_send",
            detail="message could not be confirmed",
            payload={"send_verification": {"ok": False, "reason": "unconfirmed_send"}},
            created_at=now,
        )
    )
    db_session.commit()

    with _client(db_session) as client:
        resp = client.get("/api/jobs")

    assert resp.status_code == 200
    job = resp.json()[0]
    assert job["normalized_status"] == "unconfirmed"
    assert job["status_label"] == "未确认"


def test_jobs_view_status_filter_accepts_normalized_status(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Job(
                id="job-sent",
                user_id=FakeUser.id,
                industry_slug="recruitment",
                industry_name="征兵咨询",
                type="send",
                status="done",
                progress=100,
                payload={
                    "send_summary": {"ok": True, "sent_total": 1, "failed_total": 0}
                },
                created_at=now,
                updated_at=now,
                completed_at=now,
            ),
            Job(
                id="job-unconfirmed",
                user_id=FakeUser.id,
                industry_slug="recruitment",
                industry_name="征兵咨询",
                type="send",
                status="failed",
                progress=100,
                error="unconfirmed_send",
                payload={
                    "send_summary": {"ok": False, "sent_total": 0, "failed_total": 1}
                },
                created_at=now,
                updated_at=now,
                completed_at=now,
            ),
        ]
    )
    db_session.commit()

    with _client(db_session) as client:
        resp = client.get("/api/jobs?status=sent")

    assert resp.status_code == 200
    payload = resp.json()
    assert [job["job_id"] for job in payload] == ["job-sent"]
    assert payload[0]["normalized_status"] == "sent"


def test_jobs_view_exposes_collect_queue_funnel_summary(db_session):
    now = datetime.now(timezone.utc)
    collect_summary = {
        "candidate_comments": 9,
        "classified_passed": 5,
        "enqueued": 3,
        "queue_received": 5,
        "queue_valid": 5,
        "queue_duplicates": 2,
        "queue_invalid": 0,
        "target_user_count": 2,
        "keyword_count": 12,
    }
    db_session.add(
        Job(
            id="job-collect",
            user_id=FakeUser.id,
            industry_slug="recruitment",
            industry_name="征兵咨询",
            type="collect",
            status="done",
            progress=100,
            payload={"collect_summary": collect_summary},
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
    )
    db_session.commit()

    with _client(db_session) as client:
        list_resp = client.get("/api/jobs?job_type=collect")
        detail_resp = client.get("/api/jobs/job-collect")

    assert list_resp.status_code == 200
    assert detail_resp.status_code == 200
    assert list_resp.json()[0]["collect_summary"] == collect_summary
    assert detail_resp.json()["collect_summary"] == collect_summary


def test_devices_view_merges_runtime_state_and_acceptance_entrypoints(
    db_session, monkeypatch
):
    now = datetime.now(timezone.utc)
    db_session.add(
        Device(
            id="dev-1",
            user_id=FakeUser.id,
            name="主力机",
            adb_serial="emulator-5554",
            runtime_status="offline",
            keyboard_ready=True,
            keyboard_message="ADB Keyboard active",
            last_checked_at=now,
        )
    )
    db_session.add(
        DeviceState(
            id="state-1",
            user_id=FakeUser.id,
            device_id="dev-1",
            job_id="job-live-1",
            status="running",
            current_app="com.ss.android.ugc.aweme",
            current_screen="chat",
            health={"screen_blocker": "", "screen_confidence": 0.92},
            consecutive_failures=2,
            last_heartbeat=now,
            updated_at=now,
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        "server.api.devices.run_device_acceptance",
        lambda args: {
            "correlation_id": "accept-1",
            "job_id": "accept-job-1",
            "device_id": args.serial,
            "target": args.target,
            "mode": "dry_run",
            "status": "dry_run_ready",
            "profile_matches": True,
            "health": {"online": True},
            "keyboard": {"ok": True},
            "observation": {
                "screen": "profile",
                "blocker": "",
                "screenshot_path": "data/acceptance/dry-run.png",
            },
            "before_decision": {
                "page_state": "profile_dm_ready",
                "next_action": "open_chat",
                "screenshot": "data/acceptance/dry-run.png",
            },
            "after_decision": {},
            "send_verification": {},
            "screenshot_path": "data/acceptance/dry-run.png",
            "report_path": "data/acceptance/report.json",
        },
    )

    with _client(db_session) as client:
        devices_resp = client.get("/api/devices")
        acceptance_resp = client.post(
            "/api/devices/dev-1/acceptance/dry-run",
            json={
                "industry_slug": "recruitment",
                "target": "三大小艾同学",
                "message": "验收测试，请忽略",
            },
        )

    assert devices_resp.status_code == 200
    device = devices_resp.json()[0]
    assert device["current_screen"] == "chat"
    assert device["current_app"] == "com.ss.android.ugc.aweme"
    assert device["current_job_id"] == "job-live-1"
    assert device["state_status"] == "running"
    assert device["runtime_status"] == "offline"

    assert acceptance_resp.status_code == 200
    payload = acceptance_resp.json()
    assert payload["ok"] is True
    assert payload["status"] == "dry_run_ready"
    assert payload["screenshot_path"] == "data/acceptance/dry-run.png"
    assert payload["before_decision"]["next_action"] == "open_chat"
    assert payload["after_decision"] == {}
    assert payload["send_verification"] == {}
