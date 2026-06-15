"""ADB command wrapper used by executors and API routes."""

from __future__ import annotations

import base64
import re
import subprocess
from dataclasses import dataclass

_ADB_SERIAL_RE = re.compile(r"^[a-zA-Z0-9._:\-]{1,128}$")


class ADBError(RuntimeError):
    """Raised when an ADB command cannot be executed safely."""


@dataclass(frozen=True)
class ADBResult:
    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    output: bytes = b""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def text(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def validate_adb_serial(serial: str) -> str:
    serial = str(serial or "").strip()
    if not serial or not _ADB_SERIAL_RE.match(serial):
        raise ADBError(f"Invalid ADB serial: {serial!r}")
    return serial


def parse_adb_devices(output: str) -> list[str]:
    serials: list[str] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serial = parts[0]
            if _ADB_SERIAL_RE.match(serial):
                serials.append(serial)
    return serials


class ADBClient:
    """Small validated ADB client.

    All device-level code should go through this class instead of calling
    subprocess directly. It keeps serial validation and command formatting in
    one place before the matrix executor fans out to many devices.
    """

    def __init__(self, serial: str):
        self.serial = validate_adb_serial(serial)

    @staticmethod
    def list_devices(timeout: float = 15.0) -> list[str]:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return parse_adb_devices(result.stdout + result.stderr)

    def run(
        self,
        args: list[str],
        *,
        timeout: float = 5.0,
        text: bool = True,
        check: bool = False,
    ) -> ADBResult:
        command = ["adb", "-s", self.serial, *[str(a) for a in args]]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=text,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ADBError(f"ADB command timed out: {' '.join(command)}") from exc

        adb_result = ADBResult(
            args=command,
            returncode=result.returncode,
            stdout=result.stdout if text else "",
            stderr=result.stderr if text else "",
            output=b"" if text else (result.stdout or b""),
        )
        if check and not adb_result.ok:
            detail = adb_result.text.strip() or f"returncode={adb_result.returncode}"
            raise ADBError(detail)
        return adb_result

    def shell(self, *args: str, timeout: float = 5.0, check: bool = False) -> ADBResult:
        return self.run(["shell", *args], timeout=timeout, check=check)

    def exec_out(self, *args: str, timeout: float = 5.0) -> bytes:
        result = self.run(["exec-out", *args], timeout=timeout, text=False)
        return result.output

    def tap(self, x: int, y: int) -> ADBResult:
        return self.shell("input", "tap", str(int(x)), str(int(y)), timeout=3)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> ADBResult:
        return self.shell(
            "input",
            "swipe",
            str(int(x1)),
            str(int(y1)),
            str(int(x2)),
            str(int(y2)),
            str(int(duration_ms)),
            timeout=5,
        )

    def keyevent(self, key_code: int | str) -> ADBResult:
        key = str(key_code)
        if not key.isdigit():
            raise ADBError("Keycode must be a positive integer")
        return self.shell("input", "keyevent", key, timeout=3)

    def input_text(self, text: str) -> ADBResult:
        encoded = base64.b64encode((text or "").encode("utf-8")).decode("utf-8")
        result = self.shell(
            "am",
            "broadcast",
            "-a",
            "ADB_INPUT_B64",
            "--es",
            "msg",
            encoded,
            timeout=5,
        )
        if result.ok:
            return result
        return self.shell("input", "text", text or "", timeout=5)

    def force_stop(self, package_name: str) -> ADBResult:
        if not re.match(r"^[a-zA-Z0-9_.]+$", str(package_name or "")):
            raise ADBError("Invalid Android package name")
        return self.shell("am", "force-stop", package_name, timeout=5)

    def go_home(self) -> ADBResult:
        return self.keyevent(3)

    def screen_png(self) -> bytes:
        return self.exec_out("screencap", "-p", timeout=5)

    def resolution(self) -> tuple[int, int]:
        result = self.shell("wm", "size", timeout=3)
        match = re.search(r"size:\s*(\d+)x(\d+)", result.text, re.IGNORECASE)
        if not match:
            return 1080, 1920
        return int(match.group(1)), int(match.group(2))
