"""Device health, heartbeat, and fuse management for matrix sending."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from core.agent.memory import AgentMemoryStore
from core.device.health import check_device_health


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DeviceGate:
    ok: bool
    status: str
    reason: str = ""
    health: dict[str, Any] | None = None


class DeviceSupervisor:
    """Synchronize runtime device state across sa_devices and matrix state."""

    def __init__(self, *, user_id: str = "", industry_slug: str = ""):
        self.user_id = user_id
        self.industry_slug = industry_slug
        self.memory = AgentMemoryStore(user_id=user_id, industry_slug=industry_slug)

    def preflight(self, *, device_id: str, adb_serial: str, job_id: str = "") -> DeviceGate:
        cooldown_gate = self._cooldown_gate(device_id)
        if cooldown_gate is not None:
            return cooldown_gate

        health = check_device_health(adb_serial)
        if not health.get("online"):
            reason = str(health.get("error") or "ADB device offline")[:500]
            self.mark_failure(
                device_id=device_id,
                job_id=job_id,
                status="offline",
                error=reason,
                health=health,
            )
            return DeviceGate(False, "offline", reason, health)
        self.mark_started(device_id=device_id, job_id=job_id, health=health)
        return DeviceGate(True, "running", health=health)

    def _cooldown_gate(self, device_id: str) -> DeviceGate | None:
        if not self.user_id or not device_id:
            return None
        try:
            from server.models import SessionLocal
            from server.models.device import Device
        except Exception:
            return None

        db = SessionLocal()
        try:
            device = db.query(Device).filter(
                Device.id == device_id,
                Device.user_id == self.user_id,
            ).first()
            if not device or not device.cooldown_until:
                return None
            cooldown_until = device.cooldown_until
            if cooldown_until.tzinfo is None:
                cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
            if cooldown_until > utcnow():
                reason = f"cooldown_until:{cooldown_until.isoformat()}"
                return DeviceGate(False, "cooldown", reason)

            device.cooldown_until = None
            if device.runtime_status == "cooldown":
                device.runtime_status = "idle"
            device.last_error = ""
            db.commit()
            return None
        except Exception:
            db.rollback()
            return None
        finally:
            db.close()

    def mark_started(self, *, device_id: str, job_id: str = "", health: dict | None = None) -> None:
        self._update_device(
            device_id=device_id,
            status="running",
            job_id=job_id,
            health=health,
            started=True,
            clear_error=True,
        )
        self.memory.update_device_state(
            device_id=device_id,
            job_id=job_id,
            status="running",
            health=health or {},
        )

    def heartbeat(self, *, device_id: str, job_id: str = "", health: dict | None = None) -> None:
        self._update_device(device_id=device_id, status="running", job_id=job_id, health=health)
        self.memory.update_device_state(
            device_id=device_id,
            job_id=job_id,
            status="running",
            health=health or {},
        )

    def mark_success(self, *, device_id: str, job_id: str = "", health: dict | None = None) -> None:
        self._update_device(
            device_id=device_id,
            status="running",
            job_id=job_id,
            health=health,
            failure_delta=-1,
            clear_error=True,
        )
        self.memory.update_device_state(
            device_id=device_id,
            job_id=job_id,
            status="running",
            health=health or {},
        )

    def mark_failure(
        self,
        *,
        device_id: str,
        job_id: str = "",
        status: str = "error",
        error: str = "",
        health: dict | None = None,
        cooldown_minutes: int = 0,
    ) -> None:
        cooldown_until = utcnow() + timedelta(minutes=cooldown_minutes) if cooldown_minutes else None
        self._update_device(
            device_id=device_id,
            status=status,
            job_id=job_id,
            health=health,
            error=error,
            failure_delta=1,
            cooldown_until=cooldown_until,
        )
        matrix_status = "cooldown" if cooldown_minutes else status
        self.memory.update_device_state(
            device_id=device_id,
            job_id=job_id,
            status=matrix_status,
            health={
                **(health or {}),
                "last_error": error[:500],
                "cooldown_until": cooldown_until.isoformat() if cooldown_until else "",
            },
            error=error,
        )

    def mark_cooldown(self, *, device_id: str, job_id: str = "", error: str = "", hours: int = 4) -> None:
        self.mark_failure(
            device_id=device_id,
            job_id=job_id,
            status="cooldown",
            error=error or "Device entered cooldown",
            cooldown_minutes=max(1, int(hours * 60)),
        )

    def mark_finished(self, *, device_id: str, job_id: str = "", status: str = "idle", error: str = "", force: bool = False) -> None:
        # Worker cleanup must not reopen a device that another path already quarantined.
        current = self._get_current_status(device_id)
        terminal_statuses = {"isolated", "cooldown", "offline", "keyboard_error"}
        if not force and current in terminal_statuses and status in {"idle", "running"}:
            status = current
        self._update_device(
            device_id=device_id,
            status=status,
            job_id=job_id,
            error=error,
            finished=True,
            clear_error=(not bool(error) and status in {"idle", "running"}),
        )
        self.memory.update_device_state(
            device_id=device_id,
            job_id=job_id,
            status=status,
            error=error,
        )

    def _get_current_status(self, device_id: str) -> str:
        try:
            from server.models import SessionLocal
            from server.models.device import Device
        except Exception:
            return ""
        db = SessionLocal()
        try:
            device = db.query(Device).filter(
                Device.id == device_id, Device.user_id == self.user_id,
            ).first()
            return device.runtime_status or "" if device else ""
        finally:
            db.close()

    def _update_device(
        self,
        *,
        device_id: str,
        status: str,
        job_id: str = "",
        health: dict | None = None,
        error: str = "",
        failure_delta: int = 0,
        cooldown_until: datetime | None = None,
        started: bool = False,
        finished: bool = False,
        clear_error: bool = False,
    ) -> None:
        if not self.user_id or not device_id:
            return
        try:
            from server.models import SessionLocal
            from server.models.device import Device
        except Exception:
            return

        db = SessionLocal()
        try:
            device = (
                db.query(Device)
                .filter(Device.id == device_id, Device.user_id == self.user_id)
                .first()
            )
            if not device:
                return
            device.runtime_status = status
            device.last_checked_at = utcnow()
            device.last_heartbeat = utcnow()
            if job_id:
                device.last_job_id = job_id
            if started:
                device.last_started_at = utcnow()
            if finished:
                device.last_finished_at = utcnow()
            if health is not None:
                device.keyboard_ready = bool(health.get("adb_keyboard_active"))
                device.keyboard_message = (
                    "ADB Keyboard active" if device.keyboard_ready else "ADB Keyboard not active"
                )
            if failure_delta:
                current = int(device.consecutive_failures or 0)
                if failure_delta > 0:
                    device.consecutive_failures = current + failure_delta
                else:
                    device.consecutive_failures = max(0, current + failure_delta)
            if clear_error:
                device.last_error = ""
            if error:
                device.last_error = error[:500]
            if cooldown_until:
                device.cooldown_until = cooldown_until
            elif status not in {"cooldown"} and clear_error:
                device.cooldown_until = None
            failures = int(device.consecutive_failures or 0)
            device.health_score = max(0, min(100, 100 - failures * 15))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
