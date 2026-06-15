"""Screenshot capture service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.device.adb_client import ADBClient


@dataclass(frozen=True)
class Screenshot:
    serial: str
    captured_at: str
    png: bytes
    path: str = ""


class ScreenshotService:
    def capture(self, serial: str, output_dir: str | Path | None = None) -> Screenshot:
        client = ADBClient(serial)
        png = client.screen_png()
        captured_at = datetime.now(timezone.utc).isoformat()
        path = ""
        if output_dir:
            target_dir = Path(output_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{serial.replace(':', '_')}-{captured_at.replace(':', '-')}.png"
            target = target_dir / filename
            target.write_bytes(png)
            path = str(target)
        return Screenshot(serial=serial, captured_at=captured_at, png=png, path=path)
