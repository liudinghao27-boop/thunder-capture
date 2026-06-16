import pytest
from server.schemas.industry import IndustryCreate, IndustryUpdate, IndustryOut
from server.models.industry import Industry
from core.config import IndustryConfig


def test_industry_create_has_compliance_fields():
    data = IndustryCreate(
        name="测试",
        slug="test-ind",
        compliance_mode=True,
        webhook_url="https://example.com/hook",
        auto_export_enabled=True,
    )
    assert data.compliance_mode is True
    assert data.webhook_url == "https://example.com/hook"
    assert data.auto_export_enabled is True


def test_industry_model_has_compliance_columns():
    ind = Industry(name="测试", slug="test-ind")
    assert hasattr(ind, "compliance_mode")
    assert hasattr(ind, "webhook_url")
    assert hasattr(ind, "auto_export_enabled")


def test_industry_config_has_compliance_fields():
    cfg = IndustryConfig(
        name="测试", slug="test-ind", keywords=["a"], reply_tone="测试",
        reply_style="测试", categories=["c"],
        compliance_mode=True,
        webhook_url="https://example.com/hook",
        auto_export_enabled=True,
    )
    assert cfg.compliance_mode is True
    assert cfg.webhook_url == "https://example.com/hook"
    assert cfg.auto_export_enabled is True


def test_industry_create_has_schedule_fields():
    data = IndustryCreate(
        name="测试", slug="test-schedule",
        send_start_time="09:00", send_end_time="21:00",
        pause_weekends=True, daily_send_max=100,
        effect_webhook_url="https://example.com/events",
    )
    assert data.send_start_time == "09:00"
    assert data.pause_weekends is True
    assert data.daily_send_max == 100


def test_industry_model_has_schedule_columns():
    ind = Industry(name="测试", slug="test-schedule")
    assert hasattr(ind, "send_start_time")
    assert hasattr(ind, "pause_weekends")
    assert hasattr(ind, "daily_send_max")


def test_industry_config_has_schedule_fields():
    cfg = IndustryConfig(
        name="测试", slug="test-schedule", keywords=["a"], reply_tone="测试",
        reply_style="测试", categories=["c"],
        send_start_time="10:00", send_end_time="22:00",
        pause_weekends=True, daily_send_max=200,
        effect_webhook_url="https://example.com/events",
    )
    assert cfg.send_start_time == "10:00"
    assert cfg.pause_weekends is True
    assert cfg.daily_send_max == 200


def test_industry_create_defaults():
    data = IndustryCreate(name="测试", slug="test-ind")
    assert data.compliance_mode is False
    assert data.webhook_url == ""
    assert data.auto_export_enabled is False


def test_industry_update_accepts_compliance_fields():
    data = IndustryUpdate(compliance_mode=True, webhook_url="https://x.com")
    assert data.compliance_mode is True
    assert data.webhook_url == "https://x.com"


def test_industry_out_defaults():
    out = IndustryOut(
        id="1", user_id="u1", name="测试", slug="test-ind",
        keywords=[], platforms=["douyin"], reply_tone="a", reply_style="b",
        reply_hook="", categories=[], daily_limit=15,
        video_max_age_days=14, comment_max_age_hours=48,
        llm_provider="deepseek", llm_model="deepseek-chat",
        intent_keywords=[], noise_keywords=[], target_users=[],
        is_active=True, created_at="2026-06-15T10:00:00",
    )
    assert out.compliance_mode is False
    assert out.webhook_url == ""
    assert out.auto_export_enabled is False


def test_industry_out_model_validate():
    ind = Industry(name="测试", slug="test-ind")
    # SQLAlchemy Column defaults are not populated until flush; set attrs directly.
    ind.id = "1"
    ind.user_id = "u1"
    ind.keywords = []
    ind.platforms = ["douyin"]
    ind.reply_tone = "a"
    ind.reply_style = "b"
    ind.reply_hook = ""
    ind.categories = []
    ind.daily_limit = 15
    ind.video_max_age_days = 14
    ind.comment_max_age_hours = 48
    ind.llm_provider = "deepseek"
    ind.llm_model = "deepseek-chat"
    ind.intent_keywords = []
    ind.noise_keywords = []
    ind.target_users = []
    ind.matrix_target_devices = 30
    ind.lead_inventory_days = 3
    ind.global_daily_limit = 0
    ind.auto_replenish_enabled = False
    ind.replenish_threshold_days = 1
    ind.keyword_batch_size = 12
    ind.collect_authors_per_run = 60
    ind.collect_video_limit = 120
    ind.compliance_mode = False
    ind.webhook_url = ""
    ind.auto_export_enabled = False
    ind.send_start_time = "09:00"
    ind.send_end_time = "13:00"
    ind.pause_weekends = False
    ind.daily_send_max = 0
    ind.effect_webhook_url = ""
    ind.is_active = True
    from datetime import datetime, timezone
    ind.created_at = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    out = IndustryOut.model_validate(ind)
    assert out.compliance_mode is False
    assert out.webhook_url == ""
    assert out.auto_export_enabled is False
    assert out.send_start_time == "09:00"
    assert out.pause_weekends is False
    assert out.daily_send_max == 0


def test_target_users_normalization():
    data = IndustryCreate(name="测试", slug="test-ind", target_users=[" a ", "a", "b"])
    assert data.target_users == ["a", "b"]


def test_single_platform_validation():
    with pytest.raises(ValueError):
        IndustryCreate(name="测试", slug="test-ind", platforms=["douyin", "kuaishou"])


def test_webhook_url_validator_accepts_empty_and_http():
    assert IndustryCreate(name="测试", slug="test-ind", webhook_url="").webhook_url == ""
    assert IndustryCreate(name="测试", slug="test-ind", webhook_url="https://x.com").webhook_url == "https://x.com"


def test_webhook_url_validator_rejects_invalid():
    with pytest.raises(ValueError):
        IndustryCreate(name="测试", slug="test-ind", webhook_url="not-a-url")
