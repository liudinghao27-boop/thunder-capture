"""Task stats service tests for column reference fixes."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.models import Base
from server.models.task import CollectedVideo, CollectorState, TargetBlogger


@pytest.fixture
def db(monkeypatch):
    TEST_DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    import server.models as models_module
    monkeypatch.setattr(models_module, "SessionLocal", lambda: db)

    yield db
    monkeypatch.undo()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_add_blogger_sets_discovered_at_not_created_at(db):
    from server.services.task_stats import add_blogger
    add_blogger(
        sec_uid="sec-1",
        short_id="short-1",
        nickname="nick",
        industry_slug="test-ind",
        source_keyword="kw",
        metadata='{"foo":"bar"}',
    )
    blogger = db.query(TargetBlogger).filter(TargetBlogger.sec_uid == "sec-1").first()
    assert blogger is not None
    assert blogger.discovered_at != ""
    assert blogger.nickname == "nick"


def test_mark_target_active_does_not_use_missing_updated_at(db):
    from server.services.task_stats import mark_target_active
    from datetime import datetime, timezone

    db.add(TargetBlogger(
        sec_uid="sec-2",
        industry_slug="test-ind",
        nickname="nick",
        discovered_at=datetime.now(timezone.utc).isoformat(),
        status="inactive",
    ))
    db.commit()
    # Should not raise AttributeError for updated_at
    mark_target_active("sec-2", "test-ind")
    db.expire_all()
    blogger = db.query(TargetBlogger).filter(TargetBlogger.sec_uid == "sec-2").first()
    assert blogger.status == "active"


def test_mark_target_inactive_sets_status_to_paused(db):
    from server.services.task_stats import mark_target_inactive
    from datetime import datetime, timezone

    db.add(TargetBlogger(
        sec_uid="sec-inactive",
        industry_slug="test-ind",
        nickname="nick",
        discovered_at=datetime.now(timezone.utc).isoformat(),
        status="active",
    ))
    db.commit()
    mark_target_inactive("sec-inactive", "test-ind")
    db.expire_all()
    blogger = db.query(TargetBlogger).filter(TargetBlogger.sec_uid == "sec-inactive").first()
    assert blogger.status == "paused"


def test_video_collected_uses_aweme_id(db):
    from server.services.task_stats import is_video_collected, mark_video_collected

    mark_video_collected("aweme-123", "sec-3")
    video = db.query(CollectedVideo).filter(CollectedVideo.aweme_id == "aweme-123").first()
    assert video is not None
    assert video.source_sec_uid == "sec-3"
    assert is_video_collected("aweme-123", "sec-3")
    assert not is_video_collected("aweme-missing", "sec-3")


def test_collector_state_uses_value_column(db):
    from server.services.task_stats import get_collector_state, set_collector_state

    set_collector_state("test-ind", "douyin", "cursor", {"page": 1})
    state = db.query(CollectorState).filter(
        CollectorState.industry_slug == "test-ind",
        CollectorState.platform == "douyin",
        CollectorState.key == "cursor",
    ).first()
    assert state is not None
    assert '"page": 1' in state.value

    retrieved = get_collector_state("test-ind", "douyin", "cursor")
    assert retrieved == {"page": 1}

    set_collector_state("test-ind", "douyin", "cursor", {"page": 2})
    retrieved = get_collector_state("test-ind", "douyin", "cursor")
    assert retrieved == {"page": 2}
