import json

from fastapi.testclient import TestClient

from server.auth import get_current_user
from server.main import app
from server.models.user import User


def test_evidence_file_requires_owner_metadata(tmp_path, monkeypatch):
    from server.api import devices

    base = tmp_path / "acceptance"
    base.mkdir()
    evidence = base / "shot.png"
    evidence.write_bytes(b"fakepng")
    report = base / "report.json"
    report.write_text(
        json.dumps(
            {
                "user_id": "other-user",
                "device_id": "device-1",
                "evidence_files": [str(evidence)],
            }
        ),
        encoding="utf-8",
    )
    current_user = User(
        id="current-user",
        username="current",
        password_hash="x",
        is_active=True,
    )
    monkeypatch.setattr(devices, "_ACCEPTANCE_OUTPUT_DIR", base)
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as client:
            res = client.get(
                f"/api/devices/evidence/file?path={evidence}&report_path={report}"
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 403
    assert res.json()["ok"] is False
    assert res.json()["code"] == "EVIDENCE_FORBIDDEN"


def test_evidence_file_allows_owner_metadata(tmp_path, monkeypatch):
    from server.api import devices

    base = tmp_path / "acceptance"
    base.mkdir()
    evidence = base / "shot.txt"
    evidence.write_text("evidence", encoding="utf-8")
    report = base / "report.json"
    report.write_text(
        json.dumps(
            {
                "user_id": "current-user",
                "device_id": "device-1",
                "evidence_files": [str(evidence)],
            }
        ),
        encoding="utf-8",
    )
    current_user = User(
        id="current-user",
        username="current",
        password_hash="x",
        is_active=True,
    )
    monkeypatch.setattr(devices, "_ACCEPTANCE_OUTPUT_DIR", base)
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as client:
            res = client.get(
                f"/api/devices/evidence/file?path={evidence}&report_path={report}"
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert res.text == "evidence"
