from fastapi.testclient import TestClient
from server.main import app
from server.auth import get_current_user
from server.api import industries as industries_module
import pytest

client = TestClient(app)

class FakeUser:
    id = "11111111-1111-1111-1111-111111111111"


class FakeIndustry:
    id = "ind-1"
    user_id = FakeUser.id
    name = "测试行业"
    slug = "test-industry"
    keywords = []
    platforms = ["douyin"]
    reply_tone = "业内人士"
    reply_style = "亲切专业"
    reply_hook = ""
    categories = []
    daily_limit = 15
    video_max_age_days = 14
    comment_max_age_hours = 48
    llm_provider = "deepseek"
    llm_model = "deepseek-chat"
    intent_keywords = []
    noise_keywords = []
    target_users = []
    matrix_target_devices = 30
    lead_inventory_days = 3
    global_daily_limit = 0
    auto_replenish_enabled = False
    replenish_threshold_days = 1
    keyword_batch_size = 12
    collect_authors_per_run = 60
    collect_video_limit = 120
    compliance_mode = False
    webhook_url = ""
    auto_export_enabled = False
    send_start_time = "09:00"
    send_end_time = "13:00"
    pause_weekends = False
    daily_send_max = 0
    effect_webhook_url = ""
    reply_variants = []
    is_active = True
    created_at = "2026-06-15T10:00:00"

    def __getattr__(self, name):
        return None


@pytest.fixture(autouse=True)
def override_auth(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def fake_industry(monkeypatch):
    instance = FakeIndustry()

    def _get_owned(industry_id, user, db):
        return instance

    monkeypatch.setattr(industries_module, "_get_owned_industry", _get_owned)
    return instance


@pytest.fixture
def fake_db(monkeypatch):
    import server.models as models_module

    class FakeSession:
        def commit(self):
            pass
        def refresh(self, obj):
            pass
        def close(self):
            pass

    monkeypatch.setattr(models_module, "SessionLocal", FakeSession)


def test_update_compliance_config_requires_auth():
    # Temporarily remove auth override
    app.dependency_overrides.pop(get_current_user, None)
    try:
        resp = client.put("/api/industries/ind-1/compliance-config", json={"compliance_mode": True})
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = lambda: FakeUser()


def test_webhook_test_requires_auth():
    app.dependency_overrides.pop(get_current_user, None)
    try:
        resp = client.post("/api/industries/ind-1/webhook-test")
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = lambda: FakeUser()


def test_update_compliance_config(fake_industry, fake_db):
    resp = client.put(
        "/api/industries/ind-1/compliance-config",
        json={"compliance_mode": True, "webhook_url": "https://example.com/hook", "auto_export_enabled": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["compliance_mode"] is True
    assert data["webhook_url"] == "https://example.com/hook"
    assert data["auto_export_enabled"] is True


def test_update_compliance_config_rejects_invalid_webhook_url(fake_industry, fake_db):
    resp = client.put(
        "/api/industries/ind-1/compliance-config",
        json={"webhook_url": "not-a-url"},
    )
    assert resp.status_code == 422


def test_webhook_test_without_url_returns_400(fake_industry, fake_db):
    resp = client.post("/api/industries/ind-1/webhook-test")
    assert resp.status_code == 400
    assert "Webhook" in resp.json()["detail"] or "未配置" in resp.json()["detail"]


def test_webhook_test_with_url(fake_industry, fake_db, monkeypatch):
    monkeypatch.setattr(fake_industry, "webhook_url", "https://example.com/hook")
    calls = []

    def fake_push(*, webhook_url, industry_slug, industry_name, leads):
        calls.append({"webhook_url": webhook_url, "industry_slug": industry_slug, "industry_name": industry_name, "leads": leads})
        return {"ok": True, "status_code": 200, "response_preview": "ok", "error": ""}

    monkeypatch.setattr("server.services.webhook.push_leads_to_webhook", fake_push)
    resp = client.post("/api/industries/ind-1/webhook-test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert len(calls) == 1
    assert calls[0]["webhook_url"] == "https://example.com/hook"
    assert calls[0]["industry_slug"] == "test-industry"
