"""Application error contract shared by API handlers and workers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEVICE_KEYBOARD_NOT_READY = "DEVICE_KEYBOARD_NOT_READY"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_NOT_CANCELLABLE = "JOB_NOT_CANCELLABLE"
    LEAD_NOT_FOUND = "LEAD_NOT_FOUND"
    EVIDENCE_FORBIDDEN = "EVIDENCE_FORBIDDEN"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    UPSTREAM_FAILED = "UPSTREAM_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Typed application error safe to serialize to clients."""

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str,
        detail: str = "",
        http_status: int = 400,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = str(detail or "")[:500]
        self.http_status = int(http_status or 400)
        self.context = context or {}


def serialize_error(error: AppError, *, correlation_id: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "code": error.code.value,
        "message": error.message,
        "detail": error.detail,
        "correlation_id": correlation_id,
    }
