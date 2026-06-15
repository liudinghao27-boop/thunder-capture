"""Device abstraction layer for matrix execution."""

from core.device.adb_client import ADBClient, ADBError, ADBResult, validate_adb_serial
from core.device.health import check_device_health, is_adb_keyboard_ready
from core.device.manager import MatrixDevice, load_active_devices

__all__ = [
    "ADBClient",
    "ADBError",
    "ADBResult",
    "MatrixDevice",
    "check_device_health",
    "is_adb_keyboard_ready",
    "load_active_devices",
    "validate_adb_serial",
]
