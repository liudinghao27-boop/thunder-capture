"""Device management routes."""

import re
import asyncio
from io import BytesIO
from PIL import Image
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from core.adb_keyboard import adb_device_health, prepare_adb_keyboard
from core.device.adb_client import ADBClient, ADBError, validate_adb_serial
from core.device.health import check_device_health
from server.auth import get_current_user
from server.models import get_db
from server.models.device import Device
from server.models.user import User

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Whitelist pattern for ADB serial numbers — prevents command injection
_ADB_SERIAL_RE = re.compile(r'^[a-zA-Z0-9._:\-]{1,128}$')


class DeviceCreate(BaseModel):
    name: str
    adb_serial: str
    daily_limit: int = 15
    min_interval_sec: int = 90

    @field_validator('adb_serial')
    @classmethod
    def validate_adb_serial(cls, v: str) -> str:
        try:
            validate_adb_serial(v)
        except ADBError:
            raise ValueError(f"Invalid ADB serial format: {v!r}")
        return v


class DeviceOut(BaseModel):
    id: str
    name: str
    adb_serial: str
    daily_limit: int
    min_interval_sec: int
    is_active: bool
    runtime_status: str | None = "idle"
    consecutive_failures: int | None = 0
    last_error: str | None = ""
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_checked_at: datetime | None = None
    keyboard_ready: bool | None = None
    keyboard_message: str | None = None
    health_score: int | None = 100
    cooldown_until: datetime | None = None
    last_job_id: str | None = ""

    model_config = {"from_attributes": True}


def _device_out(device: Device, keyboard_status: dict | None = None) -> DeviceOut:
    data = DeviceOut.model_validate(device)
    if keyboard_status is not None:
        data.keyboard_ready = bool(keyboard_status.get("ok"))
        data.keyboard_message = keyboard_status.get("message") or None
    return data


def _apply_keyboard_status(device: Device, status: dict):
    device.keyboard_ready = bool(status.get("ok"))
    device.keyboard_message = str(status.get("message") or "")[:256]
    device.last_checked_at = datetime.now(timezone.utc)
    if status.get("ok"):
        device.runtime_status = "idle"
        device.last_error = ""
    else:
        device.runtime_status = "keyboard_error"
        device.last_error = device.keyboard_message[:500]


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
    # Validate ADB serial format — prevent command injection
    try:
        validate_adb_serial(data.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")
    device = Device(user_id=current_user.id, **data.model_dump())
    keyboard_status = prepare_adb_keyboard(data.adb_serial, install_if_missing=True)
    _apply_keyboard_status(device, keyboard_status)
    db.add(device)
    db.commit()
    db.refresh(device)
    return _device_out(device, keyboard_status)


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
async def device_heartbeat(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Validate serial before passing to subprocess
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        return {"online": False, "serial": device.adb_serial, "error": "Invalid serial format"}

    health = await asyncio.to_thread(adb_device_health, device.adb_serial)
    online = bool(health.get("online"))

    if online:
        device.last_heartbeat = datetime.now(timezone.utc)
        
        # Check cooldown state
        from server.services.task_stats import get_wave_state
        wave = get_wave_state(device.id) or {}
        is_cooldown = False
        if wave.get("rate_limited_at"):
            try:
                limited_at = datetime.fromisoformat(wave["rate_limited_at"])
                elapsed = (datetime.now(timezone.utc) - limited_at).total_seconds()
                if elapsed < 4 * 3600:
                    is_cooldown = True
            except Exception:
                pass

        if is_cooldown:
            device.runtime_status = "cooldown"
        elif device.runtime_status in ("offline", "keyboard_error", "cooldown"):
            device.runtime_status = "idle"
            
        device.keyboard_ready = bool(health.get("adb_keyboard_active"))
        device.keyboard_message = "ADB Keyboard active" if device.keyboard_ready else "ADB Keyboard not active"
        device.last_checked_at = datetime.now(timezone.utc)
        device.last_error = ""
        db.commit()
    else:
        device.runtime_status = "offline"
        device.last_checked_at = datetime.now(timezone.utc)
        device.last_error = str(health.get("error") or "ADB heartbeat failed")[:500]
        db.commit()

    return {"online": online, "serial": device.adb_serial, "health": health}


@router.get("/{device_id}/health")
def get_device_health(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")

    health = check_device_health(device.adb_serial)
    if health.get("online"):
        device.runtime_status = "idle" if device.runtime_status == "offline" else device.runtime_status
        device.last_heartbeat = datetime.now(timezone.utc)
        device.last_error = ""
    else:
        device.runtime_status = "offline"
        device.last_error = str(health.get("error") or "ADB health failed")[:500]
    device.keyboard_ready = bool(health.get("adb_keyboard_active"))
    device.keyboard_message = "ADB Keyboard active" if device.keyboard_ready else "ADB Keyboard not active"
    device.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": bool(health.get("online")), "serial": device.adb_serial, "health": health}


@router.post("/{device_id}/prepare-keyboard", response_model=DeviceOut)
def prepare_device_keyboard(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")
    status = prepare_adb_keyboard(device.adb_serial, install_if_missing=True)
    _apply_keyboard_status(device, status)
    db.commit()
    db.refresh(device)
    return _device_out(device, status)


@router.post("/{device_id}/reset-fuse", response_model=DeviceOut)
def reset_device_fuse(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.consecutive_failures = 0
    device.last_error = ""
    device.runtime_status = "idle"
    device.health_score = 100
    device.cooldown_until = None
    device.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(device)
    return device


@router.post("/scan", response_model=list[DeviceOut])
async def scan_and_register_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        serials = await asyncio.to_thread(ADBClient.list_devices, 15.0)
    except Exception as e:
        import logging
        logging.getLogger("thunder.api").exception("Failed to execute adb scan")
        raise HTTPException(status_code=500, detail=f"Failed to execute adb scan: {str(e)}")

    # Register any newly detected devices and prepare ADB Keyboard best-effort.
    keyboard_status_by_serial = {}
    for s in serials:
        existing = db.query(Device).filter(
            Device.user_id == current_user.id,
            Device.adb_serial == s
        ).first()
        keyboard_status_by_serial[s] = await asyncio.to_thread(
            prepare_adb_keyboard, s, True
        )
        if existing:
            existing.last_heartbeat = datetime.now(timezone.utc)
            _apply_keyboard_status(existing, keyboard_status_by_serial[s])
            db.commit()
        else:
            new_dev = Device(
                user_id=current_user.id,
                name=f"自动检测设备 ({s[:8]})",
                adb_serial=s,
                daily_limit=15,
                min_interval_sec=90
            )
            _apply_keyboard_status(new_dev, keyboard_status_by_serial[s])
            db.add(new_dev)
            db.commit()

    # Return the full updated device list
    devices = (
        db.query(Device)
        .filter(Device.user_id == current_user.id)
        .order_by(Device.name)
        .all()
    )
    return [_device_out(d, keyboard_status_by_serial.get(d.adb_serial)) for d in devices]


# ── REMOTE SCREEN STREAMING & CONTROL ENDPOINTS ──────────────────

def capture_screen_as_jpeg(adb_serial: str) -> bytes | None:
    """Capture screen as PNG via ADB and convert to lightweight JPEG."""
    try:
        png_data = ADBClient(adb_serial).screen_png()
        if not png_data or len(png_data) < 100:
            return None
        # Convert PNG to JPEG with scaling for lower bandwidth and high speed
        im = Image.open(BytesIO(png_data))
        w, h = im.size
        target_w = 450
        target_h = int(h * (target_w / w))
        im = im.resize((target_w, target_h), Image.Resampling.BILINEAR)
        out = BytesIO()
        im.save(out, format="JPEG", quality=70)
        return out.getvalue()
    except Exception:
        return None


async def mjpeg_generator(adb_serial: str):
    """Generate MJPEG stream frames."""
    while True:
        frame = await asyncio.to_thread(capture_screen_as_jpeg, adb_serial)
        if frame:
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
            )
        else:
            await asyncio.sleep(0.5)
        # Target ~6 FPS
        await asyncio.sleep(0.15)


@router.get("/{device_id}/screen/stream")
async def device_screen_stream(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")
        
    return StreamingResponse(
        mjpeg_generator(device.adb_serial),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


def get_device_resolution(adb_serial: str) -> tuple[int, int]:
    """Get screen resolution using wm size."""
    try:
        return ADBClient(adb_serial).resolution()
    except Exception:
        pass
    return 1080, 1920


class ClickRequest(BaseModel):
    x_pct: float
    y_pct: float


@router.post("/{device_id}/control/click")
async def device_control_click(
    device_id: str,
    body: ClickRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")

    w, h = await asyncio.to_thread(get_device_resolution, device.adb_serial)
    real_x = int(body.x_pct * w)
    real_y = int(body.y_pct * h)

    await asyncio.to_thread(ADBClient(device.adb_serial).tap, real_x, real_y)
    return {"ok": True, "x": real_x, "y": real_y}


class SwipeRequest(BaseModel):
    x1_pct: float
    y1_pct: float
    x2_pct: float
    y2_pct: float
    duration_ms: int = 300


@router.post("/{device_id}/control/swipe")
async def device_control_swipe(
    device_id: str,
    body: SwipeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")

    w, h = await asyncio.to_thread(get_device_resolution, device.adb_serial)
    real_x1 = int(body.x1_pct * w)
    real_y1 = int(body.y1_pct * h)
    real_x2 = int(body.x2_pct * w)
    real_y2 = int(body.y2_pct * h)

    await asyncio.to_thread(
        ADBClient(device.adb_serial).swipe,
        real_x1, real_y1, real_x2, real_y2, body.duration_ms
    )
    return {"ok": True}


class KeyRequest(BaseModel):
    key_code: str


@router.post("/{device_id}/control/key")
async def device_control_key(
    device_id: str,
    body: KeyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")
    if not body.key_code.isdigit():
        raise HTTPException(status_code=400, detail="Keycode must be a positive integer")

    await asyncio.to_thread(ADBClient(device.adb_serial).keyevent, body.key_code)
    return {"ok": True}


class TextRequest(BaseModel):
    text: str


@router.post("/{device_id}/control/text")
async def device_control_text(
    device_id: str,
    body: TextRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(
        Device.id == device_id, Device.user_id == current_user.id
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")

    await asyncio.to_thread(ADBClient(device.adb_serial).input_text, body.text)
    return {"ok": True}
