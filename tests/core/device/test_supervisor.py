from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.device.supervisor import DeviceSupervisor
from server.models import Base
from server.models.device import Device
from server.models.user import User


@pytest.fixture
def supervisor_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'supervisor.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    local_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("server.models.SessionLocal", local_session)
    yield local_session
    engine.dispose()


def _seed_device(session_factory, *, cooldown_until=None, runtime_status="idle"):
    db = session_factory()
    try:
        db.add(User(id="u1", username="tester", password_hash="x", is_active=True))
        db.add(
            Device(
                id="d1",
                user_id="u1",
                name="Device 1",
                adb_serial="serial-1",
                runtime_status=runtime_status,
                cooldown_until=cooldown_until,
                consecutive_failures=2,
            )
        )
        db.commit()
    finally:
        db.close()


def test_preflight_blocks_device_while_cooldown_is_active(supervisor_db, monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    _seed_device(supervisor_db, cooldown_until=future, runtime_status="cooldown")
    health_calls = {"count": 0}

    def fake_health(_serial):
        health_calls["count"] += 1
        return {"online": True, "adb_keyboard_active": True}

    monkeypatch.setattr("core.device.supervisor.check_device_health", fake_health)

    gate = DeviceSupervisor(user_id="u1", industry_slug="test").preflight(
        device_id="d1",
        adb_serial="serial-1",
        job_id="job-1",
    )

    assert gate.ok is False
    assert gate.status == "cooldown"
    assert "cooldown_until" in gate.reason
    assert health_calls["count"] == 0


def test_preflight_clears_expired_cooldown_and_runs_health_check(
    supervisor_db, monkeypatch
):
    expired = datetime.now(timezone.utc) - timedelta(minutes=5)
    _seed_device(supervisor_db, cooldown_until=expired, runtime_status="cooldown")

    monkeypatch.setattr(
        "core.device.supervisor.check_device_health",
        lambda _serial: {"online": True, "adb_keyboard_active": True},
    )

    gate = DeviceSupervisor(user_id="u1", industry_slug="test").preflight(
        device_id="d1",
        adb_serial="serial-1",
        job_id="job-1",
    )

    assert gate.ok is True
    assert gate.status == "running"

    db = supervisor_db()
    try:
        device = db.query(Device).filter_by(id="d1").one()
        assert device.runtime_status == "running"
        assert device.cooldown_until is None
        assert device.last_error == ""
    finally:
        db.close()


def test_mark_finished_does_not_reopen_isolated_device(supervisor_db):
    _seed_device(supervisor_db, runtime_status="idle")
    supervisor = DeviceSupervisor(user_id="u1", industry_slug="test")

    supervisor.mark_failure(
        device_id="d1",
        job_id="job-1",
        status="isolated",
        error="risk_control",
    )
    supervisor.mark_finished(device_id="d1", job_id="job-1", status="idle")

    db = supervisor_db()
    try:
        device = db.query(Device).filter_by(id="d1").one()
        assert device.runtime_status == "isolated"
        assert device.last_error == "risk_control"
    finally:
        db.close()
