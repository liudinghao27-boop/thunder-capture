"""OCR adapters for screen perception.

The matrix executor uses OCR as a best-effort signal alongside Android UI XML.
The adapter is intentionally optional: if a provider is missing or its local
model files are unavailable, perception still returns structured metadata so
operators can see that OCR was skipped instead of silently losing evidence.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any


@dataclass(frozen=True)
class OCRRow:
    text: str
    confidence: float = 0.0
    box: list | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "box": self.box or [],
        }


@dataclass(frozen=True)
class OCRResult:
    provider: str
    status: str
    rows: list[OCRRow] = field(default_factory=list)
    error: str = ""

    @property
    def text(self) -> str:
        return "\n".join(row.text for row in self.rows if row.text)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "error": self.error,
            "rows": [row.as_dict() for row in self.rows],
            "text": self.text,
        }


class OCRService:
    """Best-effort OCR facade.

    Provider selection:
    - THUNDER_OCR_PROVIDER=easyocr|off|auto, default auto
    - THUNDER_OCR_DOWNLOAD=1 allows EasyOCR to download missing models
    """

    _reader = None
    _reader_error = ""
    _lock = threading.Lock()

    def __init__(self, provider: str | None = None):
        raw = provider or os.getenv("THUNDER_OCR_PROVIDER", "auto") or "auto"
        self.provider = raw.strip().lower()

    def extract(self, image_bytes: bytes) -> OCRResult:
        if not image_bytes:
            return OCRResult(provider=self.provider or "auto", status="empty_image")
        if self.provider == "off":
            return OCRResult(provider="off", status="disabled")
        return self._extract_easyocr(image_bytes)

    def extract_text(self, image_bytes: bytes) -> list[dict]:
        """Compatibility wrapper used by older perception code."""

        return [row.as_dict() for row in self.extract(image_bytes).rows]

    def _get_easyocr_reader(self):
        with self._lock:
            if self._reader is not None:
                return self._reader
            if self._reader_error:
                raise RuntimeError(self._reader_error)
            try:
                import easyocr
            except Exception as exc:  # pragma: no cover - depends on runtime env
                self._reader_error = f"easyocr not available: {exc}"
                raise RuntimeError(self._reader_error) from exc

            download_enabled = os.getenv("THUNDER_OCR_DOWNLOAD", "").strip() in {
                "1",
                "true",
                "yes",
            }
            try:
                self._reader = easyocr.Reader(
                    ["ch_sim", "en"],
                    gpu=False,
                    verbose=False,
                    download_enabled=download_enabled,
                )
                return self._reader
            except (
                Exception
            ) as exc:  # pragma: no cover - model availability is env-specific
                self._reader_error = f"easyocr init failed: {exc}"
                raise RuntimeError(self._reader_error) from exc

    def _extract_easyocr(self, image_bytes: bytes) -> OCRResult:
        try:
            from PIL import Image
            import numpy as np

            image = Image.open(BytesIO(image_bytes)).convert("RGB")
            reader = self._get_easyocr_reader()
            raw_rows = reader.readtext(np.array(image), detail=1, paragraph=False)
        except Exception as exc:
            return OCRResult(
                provider="easyocr", status="unavailable", error=str(exc)[:500]
            )

        rows: list[OCRRow] = []
        for item in raw_rows or []:
            try:
                box, text, confidence = item
            except ValueError:
                continue
            text = str(text or "").strip()
            if not text:
                continue
            rows.append(OCRRow(text=text, confidence=float(confidence or 0.0), box=box))
        return OCRResult(provider="easyocr", status="ok", rows=rows)
