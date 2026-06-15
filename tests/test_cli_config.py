"""Tests for core.config.load_industry DB preference and YAML fallback."""

import pytest

from core.config import load_industry
from server.models import Base, SessionLocal, engine
from server.models.industry import Industry
from server.models.user import User
from server.services.migrations import initialize_database


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Ensure test DB tables exist before running tests in this module."""
    initialize_database(Base, engine)


@pytest.fixture
def db_session():
    """Provide a DB session and tear down any rows created."""
    db = SessionLocal()
    yield db
    db.rollback()
    db.close()


def test_load_industry_prefers_db_over_yaml(db_session):
    """When an active Industry row exists, load_industry returns DB values."""
    user = User(
        id="u-test-1",
        username="tester",
        password_hash="x",
        is_active=True,
        deepseek_key="db-deepseek-key",
    )
    industry = Industry(
        id="i-test-1",
        user_id="u-test-1",
        name="DB Recruitment",
        slug="recruitment",
        keywords=["db-keyword"],
        platforms=["kuaishou"],
        reply_tone="DB Tone",
        reply_style="DB Style",
        reply_hook="DB Hook",
        categories=["DB Category"],
        daily_limit=99,
        video_max_age_days=7,
        comment_max_age_hours=24,
        llm_provider="openai",
        llm_model="gpt-4o",
        intent_keywords=["db-intent"],
        noise_keywords=["db-noise"],
        target_users=["db-target"],
        matrix_target_devices=10,
        lead_inventory_days=1,
        global_daily_limit=100,
        auto_replenish_enabled=True,
        replenish_threshold_days=2,
        keyword_batch_size=5,
        collect_authors_per_run=10,
        collect_video_limit=20,
        compliance_mode=True,
        webhook_url="https://example.com/webhook",
        auto_export_enabled=True,
    )

    db_session.add(user)
    db_session.add(industry)
    db_session.commit()

    cfg = load_industry("recruitment")

    assert cfg.name == "DB Recruitment"
    assert cfg.slug == "recruitment"
    assert cfg.keywords == ["db-keyword"]
    assert cfg.platforms == ["kuaishou"]
    assert cfg.reply_tone == "DB Tone"
    assert cfg.reply_style == "DB Style"
    assert cfg.reply_hook == "DB Hook"
    assert cfg.categories == ["DB Category"]
    assert cfg.daily_limit == 99
    assert cfg.video_max_age_days == 7
    assert cfg.comment_max_age_hours == 24
    assert cfg.llm_provider == "openai"
    assert cfg.llm_model == "gpt-4o"
    assert cfg.deepseek_key == "db-deepseek-key"
    assert cfg.zhipu_key == ""
    assert cfg.openai_key == ""
    assert cfg.intent_keywords == ["db-intent"]
    assert cfg.noise_keywords == ["db-noise"]
    assert cfg.target_users == ["db-target"]
    assert cfg.user_id == "u-test-1"
    assert cfg.matrix_target_devices == 10
    assert cfg.lead_inventory_days == 1
    assert cfg.global_daily_limit == 100
    assert cfg.auto_replenish_enabled is True
    assert cfg.replenish_threshold_days == 2
    assert cfg.keyword_batch_size == 5
    assert cfg.collect_authors_per_run == 10
    assert cfg.collect_video_limit == 20
    assert cfg.compliance_mode is True
    assert cfg.webhook_url == "https://example.com/webhook"
    assert cfg.auto_export_enabled is True


def test_load_industry_falls_back_to_yaml(db_session):
    """When no active DB industry exists, load_industry falls back to YAML."""
    # Ensure no active recruitment row is present
    db_session.query(Industry).filter(Industry.slug == "recruitment").delete()
    db_session.commit()

    cfg = load_industry("recruitment")

    assert cfg.name == "征兵咨询"
    assert cfg.slug == "recruitment"
    assert "参军规划" in cfg.keywords
    assert cfg.reply_tone == "退伍老兵"
