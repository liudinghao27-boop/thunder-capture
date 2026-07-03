"""Matrix device discovery and DB-backed routing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from core.config import load_system
from core.constants import DEFAULT_DAILY_LIMIT, DEFAULT_MIN_INTERVAL_SEC


@dataclass(frozen=True)
class MatrixDevice:
    id: str
    adb_serial: str
    name: str = ""
    user_id: str = ""
    daily_limit: int = DEFAULT_DAILY_LIMIT
    min_interval_sec: int = DEFAULT_MIN_INTERVAL_SEC
    runtime_status: str = "idle"
    consecutive_failures: int = 0
    cooldown_until: str = ""
    health_score: int = 100

    @classmethod
    def from_row(cls, row: dict) -> "MatrixDevice":
        return cls(
            id=str(row.get("id") or ""),
            adb_serial=str(row.get("adb_serial") or ""),
            name=str(row.get("name") or row.get("id") or ""),
            user_id=str(row.get("user_id") or ""),
            daily_limit=int(row.get("daily_limit") or DEFAULT_DAILY_LIMIT),
            min_interval_sec=int(row.get("min_interval_sec") or DEFAULT_MIN_INTERVAL_SEC),
            runtime_status=str(row.get("runtime_status") or "idle"),
            consecutive_failures=int(row.get("consecutive_failures") or 0),
            cooldown_until=str(row.get("cooldown_until") or ""),
            health_score=int(row.get("health_score") or 100),
        )

    def as_sender_dict(self) -> dict:
        return {
            "id": self.id,
            "adb_serial": self.adb_serial,
            "name": self.name,
            "user_id": self.user_id,
            "daily_limit": self.daily_limit,
            "min_interval_sec": self.min_interval_sec,
            "runtime_status": self.runtime_status,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_until": self.cooldown_until,
            "health_score": self.health_score,
        }

    def is_available(self) -> bool:
        if self.runtime_status in {"offline", "keyboard_error", "cooldown", "isolated", "running"}:
            return False
        if self.consecutive_failures >= 5:
            return False
        if self.cooldown_until:
            try:
                dt = datetime.fromisoformat(self.cooldown_until)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > datetime.now(timezone.utc):
                    return False
            except Exception:
                pass
        return True


def _load_from_server_db(user_id: str, device_ids: list[str]) -> list[MatrixDevice]:
    from server.models import SessionLocal
    from server.models.device import Device

    db = SessionLocal()
    try:
        query = db.query(Device).filter(Device.is_active.is_(True))
        if user_id:
            query = query.filter(Device.user_id == user_id)
        if device_ids:
            query = query.filter(Device.id.in_(device_ids))
        return [
            MatrixDevice.from_row(
                {
                    "id": d.id,
                    "adb_serial": d.adb_serial,
                    "name": d.name,
                    "user_id": d.user_id,
                    "daily_limit": d.daily_limit,
                    "min_interval_sec": d.min_interval_sec,
                    "runtime_status": d.runtime_status,
                    "consecutive_failures": d.consecutive_failures,
                    "cooldown_until": d.cooldown_until.isoformat() if d.cooldown_until else "",
                    "health_score": d.health_score,
                }
            )
            for d in query.order_by(Device.name).all()
        ]
    finally:
        db.close()


def _load_from_system_yaml(device_ids: list[str]) -> list[MatrixDevice]:
    devices = load_system().get("devices", [])
    selected = []
    wanted = set(device_ids)
    for item in devices:
        device = MatrixDevice.from_row(item)
        if wanted and device.id not in wanted:
            continue
        if device.is_available():
            selected.append(device)
    return selected


def load_active_devices(user_id: str = "", device_ids: list[str] | None = None) -> list[MatrixDevice]:
    requested = [str(d).strip() for d in (device_ids or []) if str(d).strip()]
    # CLI mode: always use system.yaml devices
    if not user_id:
        return _load_from_system_yaml(requested)
    # Web UI / server mode: use DB-registered devices
    try:
        devices = _load_from_server_db(user_id, requested)
    except Exception:
        return _load_from_system_yaml(requested)
    return [device for device in devices if device.is_available()]
