"""Device management routes."""

import asyncio
import json
import logging
import re
from argparse import Namespace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from core.adb_keyboard import adb_device_health, prepare_adb_keyboard
from core.device.adb_client import ADBClient, ADBError, validate_adb_serial
from core.device.health import check_device_health
from core.constants import DEFAULT_DAILY_LIMIT, DEFAULT_MIN_INTERVAL_SEC
from scripts.smoke.real_device_acceptance import run as run_device_acceptance
from server.auth import get_current_user
from server.errors import AppError, ErrorCode
from server.models import get_db
from server.models.device import Device
from server.models.matrix import DeviceState
from server.models.user import User

router = APIRouter(prefix="/api/devices", tags=["devices"])
_ACCEPTANCE_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "acceptance"

# Whitelist pattern for ADB serial numbers — prevents command injection
_ADB_SERIAL_RE = re.compile(r"^[a-zA-Z0-9._:\-]{1,128}$")


def _resolve_acceptance_evidence_path(path: str) -> Path:
    base_dir = _ACCEPTANCE_OUTPUT_DIR.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (Path(__file__).resolve().parents[2] / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.is_relative_to(base_dir):
        raise HTTPException(
            status_code=403, detail="Evidence path is outside acceptance directory"
        )
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return candidate


def _raise_device_not_found() -> None:
    raise AppError(
        code=ErrorCode.DEVICE_NOT_FOUND,
        message="Device not found",
        detail="The requested device does not exist or does not belong to current user",
        http_status=404,
    )


class DeviceCreate(BaseModel):
    name: str
    adb_serial: str
    daily_limit: int = DEFAULT_DAILY_LIMIT
    min_interval_sec: int = DEFAULT_MIN_INTERVAL_SEC

    @field_validator("adb_serial")
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
    state_status: str | None = None
    current_app: str | None = ""
    current_screen: str | None = ""
    current_job_id: str | None = ""
    state_health: dict = Field(default_factory=dict)
    state_last_heartbeat: datetime | None = None
    state_updated_at: datetime | None = None

    model_config = {"from_attributes": True}


def _device_out(
    device: Device,
    keyboard_status: dict | None = None,
    state: DeviceState | None = None,
) -> DeviceOut:
    data = DeviceOut.model_validate(device)
    if keyboard_status is not None:
        data.keyboard_ready = bool(keyboard_status.get("ok"))
        data.keyboard_message = keyboard_status.get("message") or None
    if state is not None:
        data.state_status = state.status
        data.current_app = state.current_app or ""
        data.current_screen = state.current_screen or ""
        data.current_job_id = state.job_id or ""
        data.state_health = state.health or {}
        data.state_last_heartbeat = state.last_heartbeat
        data.state_updated_at = state.updated_at
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
    devices = (
        db.query(Device)
        .filter(Device.user_id == current_user.id)
        .order_by(Device.name)
        .all()
    )
    state_map = {
        state.device_id: state
        for state in db.query(DeviceState)
        .filter(DeviceState.user_id == current_user.id)
        .all()
    }
    return [_device_out(device, state=state_map.get(device.id)) for device in devices]


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


@router.get("/evidence/file")
def get_acceptance_evidence_file(
    path: str,
    report_path: str = "",
    current_user: User = Depends(get_current_user),
):
    """Return a stored real-device acceptance evidence file."""
    evidence_path = _resolve_acceptance_evidence_path(path)
    if report_path:
        report_file = _resolve_acceptance_evidence_path(report_path)
        try:
            report = json.loads(report_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AppError(
                code=ErrorCode.EVIDENCE_FORBIDDEN,
                message="Evidence access denied",
                detail=f"Invalid evidence report metadata: {exc}",
                http_status=403,
            )
        if str(report.get("user_id") or "") != str(current_user.id):
            raise AppError(
                code=ErrorCode.EVIDENCE_FORBIDDEN,
                message="Evidence access denied",
                detail="Evidence report does not belong to current user",
                http_status=403,
            )
        allowed_files = {
            str(Path(item).resolve())
            for item in report.get("evidence_files", [])
            if str(item or "").strip()
        }
        if str(evidence_path.resolve()) not in allowed_files:
            raise AppError(
                code=ErrorCode.EVIDENCE_FORBIDDEN,
                message="Evidence access denied",
                detail="Evidence file is not referenced by the report",
                http_status=403,
            )
    return FileResponse(str(evidence_path))


@router.delete("/{device_id}")
def delete_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
    db.delete(device)
    db.commit()
    return {"ok": True}


@router.post("/{device_id}/heartbeat")
async def device_heartbeat(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()

    # Validate serial before passing to subprocess
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        return {
            "online": False,
            "serial": device.adb_serial,
            "error": "Invalid serial format",
        }

    health = await asyncio.to_thread(adb_device_health, device.adb_serial)
    online = bool(health.get("online"))

    if online:
        device.last_heartbeat = datetime.now(timezone.utc)

        # Check cooldown state
        from server.services.task_stats import get_wave_state

        wave = get_wave_state(device.id, owner_user_id=current_user.id) or {}
        is_cooldown = False
        if wave.get("rate_limited_at"):
            try:
                limited_at = datetime.fromisoformat(wave["rate_limited_at"])
                elapsed = (datetime.now(timezone.utc) - limited_at).total_seconds()
                if elapsed < 4 * 3600:
                    is_cooldown = True
            except Exception as exc:
                logging.getLogger("thunder.api.devices").debug(
                    "Cooldown parse failed: %s", exc
                )

        if is_cooldown:
            device.runtime_status = "cooldown"
        elif device.runtime_status in ("offline", "keyboard_error", "cooldown"):
            device.runtime_status = "idle"

        device.keyboard_ready = bool(health.get("adb_keyboard_active"))
        device.keyboard_message = (
            "ADB Keyboard active"
            if device.keyboard_ready
            else "ADB Keyboard not active"
        )
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
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")

    health = check_device_health(device.adb_serial)
    if health.get("online"):
        device.runtime_status = (
            "idle" if device.runtime_status == "offline" else device.runtime_status
        )
        device.last_heartbeat = datetime.now(timezone.utc)
        device.last_error = ""
    else:
        device.runtime_status = "offline"
        device.last_error = str(health.get("error") or "ADB health failed")[:500]
    device.keyboard_ready = bool(health.get("adb_keyboard_active"))
    device.keyboard_message = (
        "ADB Keyboard active" if device.keyboard_ready else "ADB Keyboard not active"
    )
    device.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "ok": bool(health.get("online")),
        "serial": device.adb_serial,
        "health": health,
    }


@router.post("/{device_id}/prepare-keyboard", response_model=DeviceOut)
def prepare_device_keyboard(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
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
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
    device.consecutive_failures = 0
    device.last_error = ""
    device.runtime_status = "idle"
    device.health_score = 100
    device.cooldown_until = None
    device.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(device)
    return device


class DeviceAcceptanceRequest(BaseModel):
    industry_slug: str
    target: str
    message: str
    confirm_target: str = ""
    max_sends: int = 1


class DeviceAcceptanceResponse(BaseModel):
    ok: bool
    status: str
    correlation_id: str
    job_id: str
    device_id: str
    target: str
    mode: str
    profile_matches: bool = False
    blocker: str | None = None
    current_screen: str | None = None
    screenshot_path: str | None = None
    report_path: str | None = None
    health: dict = Field(default_factory=dict)
    keyboard: dict = Field(default_factory=dict)
    before_decision: dict = Field(default_factory=dict)
    after_decision: dict = Field(default_factory=dict)
    send_verification: dict = Field(default_factory=dict)
    result: dict | None = None
    observation: dict | None = None


def _get_device_for_user(db: Session, user_id: str, device_id: str) -> Device:
    device = (
        db.query(Device)
        .filter(
            Device.id == device_id,
            Device.user_id == user_id,
        )
        .first()
    )
    if not device:
        _raise_device_not_found()
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")
    return device


def _serialize_acceptance_report(report: dict) -> DeviceAcceptanceResponse:
    observation = report.get("observation") or {}
    result = report.get("result")
    status = str(report.get("status") or "")
    ok = bool(report.get("ok"))
    if not ok:
        ok = status in {"dry_run_ready", "done"}
    return DeviceAcceptanceResponse(
        ok=ok,
        status=status,
        correlation_id=str(report.get("correlation_id") or ""),
        job_id=str(report.get("job_id") or ""),
        device_id=str(report.get("device_id") or ""),
        target=str(report.get("target") or ""),
        mode=str(report.get("mode") or ""),
        profile_matches=bool(report.get("profile_matches")),
        blocker=str(observation.get("blocker") or "") or None,
        current_screen=str(observation.get("screen") or "") or None,
        screenshot_path=str(
            report.get("screenshot_path") or observation.get("screenshot_path") or ""
        )
        or None,
        report_path=str(report.get("report_path") or "") or None,
        health=report.get("health") or {},
        keyboard=report.get("keyboard") or {},
        before_decision=report.get("before_decision")
        if isinstance(report.get("before_decision"), dict)
        else {},
        after_decision=report.get("after_decision")
        if isinstance(report.get("after_decision"), dict)
        else {},
        send_verification=report.get("send_verification")
        if isinstance(report.get("send_verification"), dict)
        else {},
        result=result if isinstance(result, dict) else None,
        observation=observation if isinstance(observation, dict) else None,
    )


async def _run_acceptance(
    device: Device, body: DeviceAcceptanceRequest, *, live_send: bool
) -> DeviceAcceptanceResponse:
    args = Namespace(
        serial=device.adb_serial,
        industry=body.industry_slug,
        target=body.target,
        message=body.message,
        dry_run=not live_send,
        live_send=live_send,
        confirm_target=body.confirm_target if live_send else "",
        max_sends=body.max_sends if live_send else 0,
        output_dir=_ACCEPTANCE_OUTPUT_DIR,
        user_id=device.user_id,
        device_id=device.id,
    )
    try:
        report = await asyncio.to_thread(run_device_acceptance, args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return _serialize_acceptance_report(report)


@router.post("/{device_id}/acceptance/dry-run", response_model=DeviceAcceptanceResponse)
async def run_device_dry_run(
    device_id: str,
    body: DeviceAcceptanceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = _get_device_for_user(db, current_user.id, device_id)
    return await _run_acceptance(device, body, live_send=False)


@router.post(
    "/{device_id}/acceptance/live-send", response_model=DeviceAcceptanceResponse
)
async def run_device_live_send(
    device_id: str,
    body: DeviceAcceptanceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = _get_device_for_user(db, current_user.id, device_id)
    return await _run_acceptance(device, body, live_send=True)


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
        raise HTTPException(
            status_code=500, detail=f"Failed to execute adb scan: {str(e)}"
        )

    # Register any newly detected devices and prepare ADB Keyboard best-effort.
    keyboard_status_by_serial = {}
    for s in serials:
        existing = (
            db.query(Device)
            .filter(Device.user_id == current_user.id, Device.adb_serial == s)
            .first()
        )
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
                daily_limit=DEFAULT_DAILY_LIMIT,
                min_interval_sec=DEFAULT_MIN_INTERVAL_SEC,
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
    return [
        _device_out(d, keyboard_status_by_serial.get(d.adb_serial)) for d in devices
    ]


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
        im = im.resize((target_w, target_h), Image.Resampling.BILINEAR)  # type: ignore[assignment]
        out = BytesIO()
        im.save(out, format="JPEG", quality=70)
        return out.getvalue()
    except Exception as exc:
        logging.getLogger("thunder.api.devices").warning(
            "Screen capture failed: %s", exc
        )
        return None


async def mjpeg_generator(adb_serial: str):
    """Generate MJPEG stream frames."""
    while True:
        frame = await asyncio.to_thread(capture_screen_as_jpeg, adb_serial)
        if frame:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
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
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")

    logging.getLogger("thunder.audit.devices").info(
        "screen_stream_opened user_id=%s device_id=%s adb_serial=%s",
        current_user.id,
        device.id,
        device.adb_serial,
    )
    return StreamingResponse(
        mjpeg_generator(device.adb_serial),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def get_device_resolution(adb_serial: str) -> tuple[int, int]:
    """Get screen resolution using wm size."""
    try:
        return ADBClient(adb_serial).resolution()
    except Exception as exc:
        logging.getLogger("thunder.api.devices").debug(
            "Resolution check failed for %s: %s", adb_serial, exc
        )
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
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
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
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
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
        real_x1,
        real_y1,
        real_x2,
        real_y2,
        body.duration_ms,
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
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")
    if not body.key_code.isdigit():
        raise HTTPException(
            status_code=400, detail="Keycode must be a positive integer"
        )

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
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        _raise_device_not_found()
    try:
        validate_adb_serial(device.adb_serial)
    except ADBError:
        raise HTTPException(status_code=400, detail="Invalid ADB serial format")

    await asyncio.to_thread(ADBClient(device.adb_serial).input_text, body.text)
    return {"ok": True}
