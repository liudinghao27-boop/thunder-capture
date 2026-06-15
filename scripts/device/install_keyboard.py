"""Prepare ADB Keyboard on all currently connected Android devices."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.adb_keyboard import prepare_adb_keyboard  # noqa: E402


def connected_devices() -> list[str]:
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=15)
    devices = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def main() -> int:
    devices = connected_devices()
    print(f"Found connected devices: {devices}")
    if not devices:
        return 0

    exit_code = 0
    for serial in devices:
        status = prepare_adb_keyboard(serial, install_if_missing=True)
        state = "OK" if status["ok"] else "FAILED"
        print(f"{serial}: {state} - {status.get('message') or ''}")
        if not status["ok"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
