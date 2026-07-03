from fastapi.testclient import TestClient

from server.errors import AppError, ErrorCode, serialize_error
from server.main import app


def test_app_error_serializes_without_sensitive_traceback():
    err = AppError(
        code=ErrorCode.DEVICE_OFFLINE,
        message="Device offline",
        detail="adb serial abc failed",
        http_status=409,
    )

    payload = serialize_error(err, correlation_id="cid-1")

    assert payload == {
        "ok": False,
        "code": "DEVICE_OFFLINE",
        "message": "Device offline",
        "detail": "adb serial abc failed",
        "correlation_id": "cid-1",
    }


def test_app_error_handler_returns_standard_payload():
    route = "/__test_app_error"

    @app.get(route)
    def _raise_app_error():
        raise AppError(
            code=ErrorCode.QUOTA_EXHAUSTED,
            message="Quota exhausted",
            detail="daily limit reached",
            http_status=409,
        )

    with TestClient(app) as client:
        response = client.get(route)

    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert response.json()["code"] == "QUOTA_EXHAUSTED"
    assert response.json()["message"] == "Quota exhausted"
    assert response.json()["detail"] == "daily limit reached"
    assert "correlation_id" in response.json()
