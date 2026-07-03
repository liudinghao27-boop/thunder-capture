"""ADB keyboard setup helpers for Android automation devices."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("thunder.adb_keyboard")

ADB_KEYBOARD_PACKAGE = "com.android.adbkeyboard"
ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"
_ADB_SERIAL_RE = re.compile(r"^[a-zA-Z0-9._:\-]{1,128}$")


def validate_adb_serial(serial: str) -> str:
    if not serial or not _ADB_SERIAL_RE.match(serial):
        raise ValueError(f"Invalid ADB serial: {serial!r}")
    return serial


def _apk_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "ADBKeyboard.apk"


def _run_adb(serial: str, args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    validate_adb_serial(serial)
    return subprocess.run(
        ["adb", "-s", serial, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def is_adb_keyboard_installed(serial: str) -> bool:
    result = _run_adb(
        serial,
        ["shell", "pm", "list", "packages", ADB_KEYBOARD_PACKAGE],
        timeout=5,
    )
    return ADB_KEYBOARD_PACKAGE in (result.stdout + result.stderr)


def is_adb_keyboard_active(serial: str) -> bool:
    try:
        result = _run_adb(serial, ["shell", "ime", "list", "-s"], timeout=5)
        if ADB_KEYBOARD_PACKAGE.lower() in (result.stdout + result.stderr).lower():
            return True
    except subprocess.TimeoutExpired:
        raise
    except Exception:
        pass

    result = _run_adb(
        serial,
        ["shell", "settings", "get", "secure", "default_input_method"],
        timeout=5,
    )
    return ADB_KEYBOARD_PACKAGE.lower() in (result.stdout + result.stderr).lower()


def install_adb_keyboard(serial: str) -> tuple[bool, str]:
    apk = _apk_path()
    if not apk.exists():
        return False, f"ADBKeyboard.apk not found: {apk}"

    try:
        result = _run_adb(serial, ["install", "-r", str(apk)], timeout=30)
    except subprocess.TimeoutExpired:
        return False, "install timed out; check USB install permission on the phone"

    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0 or "success" in output.lower():
        return True, output or "installed"

    if "INSTALL_FAILED_VERSION_DOWNGRADE" in output:
        try:
            retry = _run_adb(serial, ["install", "-r", "-d", str(apk)], timeout=30)
        except subprocess.TimeoutExpired:
            return False, "install downgrade retry timed out; check USB install permission on the phone"
        retry_output = (retry.stdout + retry.stderr).strip()
        if retry.returncode == 0 or "success" in retry_output.lower():
            return True, retry_output or "installed with downgrade flag"
        return False, retry_output or f"adb install -d failed with code {retry.returncode}"

    if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in output:
        try:
            uninstall = _run_adb(serial, ["uninstall", ADB_KEYBOARD_PACKAGE], timeout=20)
            reinstall = _run_adb(serial, ["install", "-r", str(apk)], timeout=30)
        except subprocess.TimeoutExpired:
            return False, "install incompatible retry timed out"
        uninstall_output = (uninstall.stdout + uninstall.stderr).strip()
        reinstall_output = (reinstall.stdout + reinstall.stderr).strip()
        if reinstall.returncode == 0 or "success" in reinstall_output.lower():
            return True, "; ".join(
                part for part in [uninstall_output or "uninstalled incompatible package", reinstall_output] if part
            )
        return False, reinstall_output or f"adb reinstall failed with code {reinstall.returncode}"

    return False, output or f"adb install failed with code {result.returncode}"


def enable_adb_keyboard(serial: str) -> tuple[bool, str]:
    messages = []
    try:
        package_enable = _run_adb(
            serial,
            ["shell", "pm", "enable", ADB_KEYBOARD_PACKAGE],
            timeout=8,
        )
        messages.append((package_enable.stdout + package_enable.stderr).strip())
    except subprocess.TimeoutExpired:
        return False, "package enable timed out"

    try:
        enable = _run_adb(
            serial,
            ["shell", "ime", "enable", ADB_KEYBOARD_IME],
            timeout=8,
        )
        messages.append((enable.stdout + enable.stderr).strip())
    except subprocess.TimeoutExpired:
        return False, "ime enable timed out"

    try:
        set_default = _run_adb(
            serial,
            ["shell", "ime", "set", ADB_KEYBOARD_IME],
            timeout=8,
        )
        messages.append((set_default.stdout + set_default.stderr).strip())
    except subprocess.TimeoutExpired:
        return False, "ime set timed out"

    if is_adb_keyboard_active(serial):
        return True, "; ".join(m for m in messages if m) or "enabled"
    return False, "; ".join(m for m in messages if m) or "keyboard not active"


def prepare_adb_keyboard(serial: str, install_if_missing: bool = True) -> dict:
    """Ensure ADB Keyboard is installed and selected for one device."""
    validate_adb_serial(serial)
    result = {
        "serial": serial,
        "installed": False,
        "active": False,
        "ok": False,
        "message": "",
    }

    try:
        installed = is_adb_keyboard_installed(serial)
        result["installed"] = installed
        if not installed:
            if not install_if_missing:
                result["message"] = "ADB Keyboard not installed"
                return result
            installed, message = install_adb_keyboard(serial)
            result["installed"] = installed
            result["message"] = message
            if not installed:
                return result

        active = is_adb_keyboard_active(serial)
        result["active"] = active
        if not active:
            active, message = enable_adb_keyboard(serial)
            result["active"] = active
            result["message"] = message

        result["ok"] = bool(result["installed"] and result["active"])
        if result["ok"] and not result["message"]:
            result["message"] = "ADB Keyboard ready"
        return result
    except subprocess.TimeoutExpired:
        result["message"] = "ADB command timed out"
        return result
    except Exception as exc:
        log.debug("ADB Keyboard preparation failed for %s", serial, exc_info=True)
        result["message"] = str(exc)
        return result


def adb_device_health(serial: str) -> dict[str, Any]:
    """Return lightweight ADB health details for UI diagnostics."""
    validate_adb_serial(serial)
    health: dict[str, Any] = {
        "serial": serial,
        "online": False,
        "boot_completed": False,
        "model": "",
        "android_version": "",
        "battery_level": None,
        "default_ime": "",
        "adb_keyboard_active": False,
        "error": "",
    }
    try:
        echo = _run_adb(serial, ["shell", "echo", "ok"], timeout=5)
        output = (echo.stdout + echo.stderr).lower()
        health["online"] = echo.returncode == 0 and "ok" in output
        if not health["online"]:
            health["error"] = (echo.stdout + echo.stderr).strip() or "ADB echo failed"
            return health

        model = _run_adb(serial, ["shell", "getprop", "ro.product.model"], timeout=5)
        version = _run_adb(serial, ["shell", "getprop", "ro.build.version.release"], timeout=5)
        boot = _run_adb(serial, ["shell", "getprop", "sys.boot_completed"], timeout=5)
        ime = _run_adb(serial, ["shell", "settings", "get", "secure", "default_input_method"], timeout=5)
        battery = _run_adb(serial, ["shell", "dumpsys", "battery"], timeout=8)

        health["model"] = model.stdout.strip()
        health["android_version"] = version.stdout.strip()
        health["boot_completed"] = boot.stdout.strip() == "1"
        health["default_ime"] = ime.stdout.strip()
        health["adb_keyboard_active"] = ADB_KEYBOARD_PACKAGE.lower() in health["default_ime"].lower()

        for line in battery.stdout.splitlines():
            if "level:" in line.lower():
                try:
                    health["battery_level"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
                break
        return health
    except subprocess.TimeoutExpired:
        health["error"] = "ADB health check timed out"
        return health
    except Exception as exc:
        health["error"] = str(exc)
        return health
