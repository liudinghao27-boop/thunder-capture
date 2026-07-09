"""Screen perception facade."""

from __future__ import annotations

import re
from pathlib import Path

from core.agent.state import Observation, utc_now
from core.device.adb_client import ADBClient
from core.vision.ocr import OCRService
from core.vision.screenshot import ScreenshotService
from core.vision.ui_parser import UIParser


class PerceptionService:
    def __init__(
        self,
        screenshot_service: ScreenshotService | None = None,
        ui_parser: UIParser | None = None,
        ocr: OCRService | None = None,
    ):
        self.screenshot_service = screenshot_service or ScreenshotService()
        self.ui_parser = ui_parser or UIParser()
        self.ocr = ocr or OCRService()

    def observe(
        self,
        *,
        device_id: str,
        adb_serial: str,
        screenshot_dir: str | Path | None = None,
    ) -> Observation:
        screenshot = None
        elements = []
        ocr_text = ""
        ocr_status = ""
        ocr_provider = ""
        package_name = ""
        activity = ""
        errors: list[str] = []

        try:
            screenshot = self.screenshot_service.capture(adb_serial, screenshot_dir)
        except Exception as exc:
            errors.append(f"screenshot_error: {str(exc)[:240]}")

        if screenshot:
            ocr_result = self.ocr.extract(screenshot.png)
            ocr_text = ocr_result.text
            ocr_status = ocr_result.status
            ocr_provider = ocr_result.provider
            if ocr_result.error:
                errors.append(f"ocr_error: {ocr_result.error[:240]}")

        try:
            package_name, activity = self._current_focus(adb_serial)
        except Exception as exc:
            errors.append(f"focus_error: {str(exc)[:240]}")

        try:
            xml = self.ui_parser.dump_xml(adb_serial)
            parsed = self.ui_parser.parse(xml)
            elements = [e.as_dict() for e in parsed[:200]]
            state = self.ui_parser.infer_screen(
                parsed,
                ocr_text=ocr_text,
                package_name=package_name,
                activity=activity,
            )
        except Exception as exc:
            errors.append(f"ui_xml_error: {str(exc)[:240]}")
            state = self.ui_parser.infer_screen(
                [],
                ocr_text=ocr_text,
                package_name=package_name,
                activity=activity,
            )

        return Observation(
            device_id=device_id,
            adb_serial=adb_serial,
            screen=state.screen,
            confidence=state.confidence,
            blocker=state.blocker,
            evidence=state.evidence,
            elements=elements,
            screenshot_path=screenshot.path if screenshot else "",
            ocr_text=ocr_text,
            ocr_status=ocr_status,
            ocr_provider=ocr_provider,
            package_name=package_name,
            activity=activity,
            errors=errors,
            captured_at=screenshot.captured_at if screenshot else utc_now(),
        )

    def _current_focus(self, adb_serial: str) -> tuple[str, str]:
        client = ADBClient(adb_serial)
        for args in (("dumpsys", "window", "windows"), ("dumpsys", "window")):
            result = client.shell(*args, timeout=5)
            focused = self._parse_focused_component(result.text)
            if focused != ("", ""):
                return focused
        return "", ""

    def _parse_focused_component(self, text: str) -> tuple[str, str]:
        patterns = [
            r"mCurrentFocus=.*?\s([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.$]+)",
            r"mFocusedApp=.*?\s([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.$]+)",
            r"mResumedActivity:.*?\s([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.$]+)",
            r"ResumedActivity:.*?\s([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.$]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text or "")
            if not match:
                continue
            package_name, activity = match.group(1), match.group(2)
            if activity.startswith("."):
                activity = f"{package_name}{activity}"
            return package_name, activity
        return "", ""

    def save_snapshot(
        self,
        observation,
        *,
        user_id: str = "",
        device_id: str = "",
        job_id: str = "",
        task_id: str = "",
        stage: str = "",
    ) -> str:
        """Persist an Observation to the ScreenSnapshot table (best-effort)."""
        try:
            from server.models import SessionLocal
            from server.models.matrix import ScreenSnapshot
        except Exception:
            return ""
        db = SessionLocal()
        try:
            ScreenSnapshot.__table__.create(bind=db.get_bind(), checkfirst=True)
            snap = ScreenSnapshot(
                user_id=user_id,
                device_id=device_id,
                job_id=job_id or None,
                task_id=task_id or None,
                stage=stage or "",
                screen_name=observation.screen or "",
                blocker=observation.blocker or "",
                ocr_text=(observation.ocr_text or "")[:2000],
                image_path=observation.screenshot_path or "",
                confidence=int((observation.confidence or 0) * 100),
            )
            db.add(snap)
            db.commit()
            return snap.id
        except Exception:
            db.rollback()
            return ""
        finally:
            db.close()
