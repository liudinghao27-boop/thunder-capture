"""License manager — device-based authorization.

For commercial deployment, replace this stub with real license validation.
"""

import os
import hashlib
import datetime
import json
from pathlib import Path

LICENSE_FILE = Path(__file__).resolve().parent.parent / "data" / ".license"


def generate_device_id() -> str:
    """Generate unique device fingerprint."""
    import platform
    import uuid
    raw = f"{platform.node()}-{platform.processor()}-{uuid.getnode()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def check_license() -> dict:
    """Check if the current installation is authorized.

    Returns:
        {"valid": True/False, "devices": 5, "expires": "2026-12-31", "reason": ""}
    """
    if not LICENSE_FILE.exists():
        return {
            "valid": False,
            "reason": "未找到授权文件。请联系商务获取 license.key。"
        }

    try:
        with open(LICENSE_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return {"valid": False, "reason": "授权文件损坏"}

    # Check device binding
    device_id = data.get("device_id", "")
    if device_id and device_id != generate_device_id():
        return {"valid": False, "reason": "授权文件与当前设备不匹配"}

    # Check expiration
    expires = data.get("expires", "")
    if expires:
        try:
            exp_date = datetime.date.fromisoformat(expires)
            if datetime.date.today() > exp_date:
                return {
                    "valid": False,
                    "reason": f"授权已于 {expires} 到期",
                    "expires": expires,
                }
        except ValueError:
            pass

    return {
        "valid": True,
        "devices": data.get("max_devices", 5),
        "expires": data.get("expires", "永久"),
    }


def activate_license(key: str) -> bool:
    """Activate with a license key. In production, validates against your server."""
    # Stub: accept any 32-char key for dev
    if len(key) < 16:
        return False

    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LICENSE_FILE, "w") as f:
        json.dump({
            "key_hash": hashlib.sha256(key.encode()).hexdigest()[:12],
            "device_id": generate_device_id(),
            "max_devices": 5,
            "expires": (datetime.date.today() + datetime.timedelta(days=365)).isoformat(),
            "activated_at": datetime.date.today().isoformat(),
        }, f, indent=2)
    return True
