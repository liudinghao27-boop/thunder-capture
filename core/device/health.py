"""Device health probes for the matrix layer."""

from __future__ import annotations

from core.adb_keyboard import ADB_KEYBOARD_PACKAGE, adb_device_health
from core.device.adb_client import ADBClient, ADBError


def is_adb_keyboard_ready(serial: str) -> bool:
    try:
        client = ADBClient(serial)
        ime = client.shell(
            "settings", "get", "secure", "default_input_method", timeout=5
        )
        return ADB_KEYBOARD_PACKAGE.lower() in ime.text.lower()
    except ADBError:
        return False


def check_device_health(serial: str) -> dict:
    health = adb_device_health(serial)
    health["adb_keyboard_active"] = bool(
        health.get("adb_keyboard_active") or is_adb_keyboard_ready(serial)
    )
    return health
