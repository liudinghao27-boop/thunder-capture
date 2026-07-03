import subprocess
from pathlib import Path

from core import adb_keyboard


def test_install_adb_keyboard_retries_with_downgrade_flag(monkeypatch, tmp_path):
    apk = tmp_path / "ADBKeyboard.apk"
    apk.write_bytes(b"apk")
    calls = []

    def fake_apk_path() -> Path:
        return apk

    def fake_run(serial, args, timeout=8.0):
        calls.append(args)
        if args == ["install", "-r", str(apk)]:
            return subprocess.CompletedProcess(
                ["adb"],
                1,
                stdout="",
                stderr="INSTALL_FAILED_VERSION_DOWNGRADE",
            )
        return subprocess.CompletedProcess(["adb"], 0, stdout="Success", stderr="")

    monkeypatch.setattr(adb_keyboard, "_apk_path", fake_apk_path)
    monkeypatch.setattr(adb_keyboard, "_run_adb", fake_run)

    ok, message = adb_keyboard.install_adb_keyboard("device-1")

    assert ok is True
    assert "Success" in message
    assert calls == [
        ["install", "-r", str(apk)],
        ["install", "-r", "-d", str(apk)],
    ]


def test_install_adb_keyboard_uninstalls_incompatible_signature(monkeypatch, tmp_path):
    apk = tmp_path / "ADBKeyboard.apk"
    apk.write_bytes(b"apk")
    calls = []

    def fake_apk_path() -> Path:
        return apk

    def fake_run(serial, args, timeout=8.0):
        calls.append(args)
        if args == ["install", "-r", str(apk)] and len(calls) == 1:
            return subprocess.CompletedProcess(
                ["adb"],
                1,
                stdout="",
                stderr="INSTALL_FAILED_UPDATE_INCOMPATIBLE",
            )
        return subprocess.CompletedProcess(["adb"], 0, stdout="Success", stderr="")

    monkeypatch.setattr(adb_keyboard, "_apk_path", fake_apk_path)
    monkeypatch.setattr(adb_keyboard, "_run_adb", fake_run)

    ok, message = adb_keyboard.install_adb_keyboard("device-1")

    assert ok is True
    assert "Success" in message
    assert calls == [
        ["install", "-r", str(apk)],
        ["uninstall", adb_keyboard.ADB_KEYBOARD_PACKAGE],
        ["install", "-r", str(apk)],
    ]


def test_enable_adb_keyboard_enables_package_before_ime(monkeypatch):
    calls = []

    def fake_run(serial, args, timeout=8.0):
        calls.append(args)
        return subprocess.CompletedProcess(["adb"], 0, stdout="Success", stderr="")

    monkeypatch.setattr(adb_keyboard, "_run_adb", fake_run)
    monkeypatch.setattr(adb_keyboard, "is_adb_keyboard_active", lambda serial: True)

    ok, _message = adb_keyboard.enable_adb_keyboard("device-1")

    assert ok is True
    assert calls[:3] == [
        ["shell", "pm", "enable", adb_keyboard.ADB_KEYBOARD_PACKAGE],
        ["shell", "ime", "enable", adb_keyboard.ADB_KEYBOARD_IME],
        ["shell", "ime", "set", adb_keyboard.ADB_KEYBOARD_IME],
    ]
