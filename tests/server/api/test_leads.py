import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from server.main import app
from server.auth import get_current_user
from server.api.leads import router as leads_router, export_leads, LeadExportRequest

client = TestClient(app)


class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


class FakeRow:
    id = 1
    platform = "douyin"
    keyword = "当兵"
    source_creator = "兵爸"
    source_video_desc = ""
    user_name = "u1"
    unique_id = "uid1"
    short_id = ""
    douyin_id = ""
    text = "我想当兵"
    matched_categories = "[]"
    ai_reply = ""
    status = "pending"
    error = ""
    fetched_at = "2026-06-15T10:00:00"
    processed_at = ""
    owner_user_id = ""

    def __getattr__(self, name):
        return ""


class FakeQuery:
    def filter(self, *a, **k):
        return self

    def count(self):
        return 1

    def order_by(self, *a):
        return self

    def limit(self, n):
        return self

    def offset(self, n):
        return self

    def all(self):
        return [FakeRow()]


class FakeSession:
    def query(self, model):
        return FakeQuery()

    def close(self):
        pass


@pytest.fixture(autouse=True)
def override_auth(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def fake_session(monkeypatch):
    import server.models as models_module

    monkeypatch.setattr(models_module, "SessionLocal", FakeSession)


def test_export_csv_requires_auth():
    app.dependency_overrides.pop(get_current_user, None)
    resp = client.post(
        "/api/leads/export", json={"industry_slug": "recruitment", "format": "csv"}
    )
    assert resp.status_code in (401, 403)


def test_export_csv_returns_file(fake_session):
    resp = client.post(
        "/api/leads/export", json={"industry_slug": "recruitment", "format": "csv"}
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "我想当兵" in resp.text


def test_export_xlsx_returns_file(fake_session):
    resp = client.post(
        "/api/leads/export", json={"industry_slug": "recruitment", "format": "xlsx"}
    )
    assert resp.status_code == 200
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        in resp.headers.get("content-type", "")
    )
    assert resp.content.startswith(b"PK")


def test_export_invalid_format_returns_400(fake_session):
    req = LeadExportRequest.model_construct(
        industry_slug="recruitment", format="pdf"
    )
    with pytest.raises(HTTPException) as exc_info:
        export_leads(req, FakeUser())
    assert exc_info.value.status_code == 400
