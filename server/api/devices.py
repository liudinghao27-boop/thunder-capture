"""Device management routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import get_db
from server.models.device import Device
from server.models.user import User

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceCreate(BaseModel):
    name: str
    adb_serial: str
    daily_limit: int = 15
    min_interval_sec: int = 90


class DeviceOut(BaseModel):
    id: str
    name: str
    adb_serial: str
    daily_limit: int
    min_interval_sec: int
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[DeviceOut])
def list_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Device)
        .filter(Device.user_id == current_user.id)
        .order_by(Device.name)
        .all()
    )


@router.post("", response_model=DeviceOut, status_code=201)
def create_device(
    data: DeviceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = Device(user_id=current_user.id, **data.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}")
def delete_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return {"ok": True}


@router.post("/{device_id}/heartbeat")
def device_heartbeat(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.last_heartbeat = datetime.now(timezone.utc)
    db.commit()

    # Check ADB connectivity
    import subprocess
    try:
        r = subprocess.run(
            ["adb", "-s", device.adb_serial, "shell", "echo", "ok"],
            capture_output=True, text=True, timeout=5,
        )
        online = "ok" in (r.stdout + r.stderr)
    except Exception:
        online = False

    return {"online": online, "serial": device.adb_serial}

