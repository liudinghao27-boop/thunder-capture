import pytest
from fastapi import HTTPException

from server.api import devices


def test_resolve_acceptance_evidence_path_allows_acceptance_file(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "acceptance"
    evidence_dir.mkdir()
    screenshot = evidence_dir / "shot.png"
    screenshot.write_bytes(b"png")
    monkeypatch.setattr(devices, "_ACCEPTANCE_OUTPUT_DIR", evidence_dir)

    assert (
        devices._resolve_acceptance_evidence_path(str(screenshot))
        == screenshot.resolve()
    )


def test_resolve_acceptance_evidence_path_blocks_outside_path(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "acceptance"
    evidence_dir.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    monkeypatch.setattr(devices, "_ACCEPTANCE_OUTPUT_DIR", evidence_dir)

    with pytest.raises(HTTPException) as exc:
        devices._resolve_acceptance_evidence_path(str(outside))

    assert exc.value.status_code == 403
