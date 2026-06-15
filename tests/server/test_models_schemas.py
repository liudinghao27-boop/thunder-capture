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
