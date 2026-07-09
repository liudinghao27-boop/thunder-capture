"""Task stats service tests for column reference fixes."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.models import Base
from server.models.task import CollectedVideo, CollectorState, TargetBlogger, TaskQueue


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
        owner_user_id="u1",
    )
    blogger = db.query(TargetBlogger).filter(TargetBlogger.sec_uid == "sec-1").first()
    assert blogger is not None
    assert blogger.discovered_at != ""
    assert blogger.nickname == "nick"
    assert blogger.owner_user_id == "u1"


def test_mark_target_active_does_not_use_missing_updated_at(db):
    from server.services.task_stats import mark_target_active
    from datetime import datetime, timezone

    db.add(
        TargetBlogger(
            sec_uid="sec-2",
            industry_slug="test-ind",
            owner_user_id="u1",
            nickname="nick",
            discovered_at=datetime.now(timezone.utc).isoformat(),
            status="inactive",
        )
    )
    db.commit()
    # Should not raise AttributeError for updated_at
    mark_target_active("sec-2", "test-ind", owner_user_id="u1")
    db.expire_all()
    blogger = db.query(TargetBlogger).filter(TargetBlogger.sec_uid == "sec-2").first()
    assert blogger.status == "active"


def test_mark_target_inactive_sets_status_to_paused(db):
    from server.services.task_stats import mark_target_inactive
    from datetime import datetime, timezone

    db.add(
        TargetBlogger(
            sec_uid="sec-inactive",
            industry_slug="test-ind",
            owner_user_id="u1",
            nickname="nick",
            discovered_at=datetime.now(timezone.utc).isoformat(),
            status="active",
        )
    )
    db.commit()
    mark_target_inactive("sec-inactive", "test-ind", owner_user_id="u1")
    db.expire_all()
    blogger = (
        db.query(TargetBlogger).filter(TargetBlogger.sec_uid == "sec-inactive").first()
    )
    assert blogger.status == "paused"


def test_video_collected_uses_aweme_id(db):
    from server.services.task_stats import is_video_collected, mark_video_collected

    mark_video_collected("aweme-123", "sec-3", owner_user_id="u1")
    video = (
        db.query(CollectedVideo).filter(CollectedVideo.aweme_id == "aweme-123").first()
    )
    assert video is not None
    assert video.source_sec_uid == "sec-3"
    assert video.owner_user_id == "u1"
    assert is_video_collected("aweme-123", "sec-3", owner_user_id="u1")
    assert not is_video_collected("aweme-missing", "sec-3", owner_user_id="u1")


def test_collector_state_uses_value_column(db):
    from server.services.task_stats import get_collector_state, set_collector_state

    set_collector_state("test-ind", "douyin", "cursor", {"page": 1}, owner_user_id="u1")
    state = (
        db.query(CollectorState)
        .filter(
            CollectorState.industry_slug == "test-ind",
            CollectorState.platform == "douyin",
            CollectorState.key == "cursor",
        )
        .first()
    )
    assert state is not None
    assert state.owner_user_id == "u1"
    assert '"page": 1' in state.value

    retrieved = get_collector_state("test-ind", "douyin", "cursor", owner_user_id="u1")
    assert retrieved == {"page": 1}

    set_collector_state("test-ind", "douyin", "cursor", {"page": 2}, owner_user_id="u1")
    retrieved = get_collector_state("test-ind", "douyin", "cursor", owner_user_id="u1")
    assert retrieved == {"page": 2}


def test_enqueue_tasks_batch_result_reports_inserted_and_duplicates(db, monkeypatch):
    import server.models as models_module

    monkeypatch.setattr(models_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(models_module, "engine", db.get_bind())

    from server.services.task_stats import enqueue_tasks_batch_result

    comments = [
        {
            "industry_slug": "test-ind",
            "text": "想咨询报名流程",
            "source_name": "user-a",
            "source_sec_uid": "sec-a",
            "source_short_id": "comment-1",
            "source_video_id": "video-1",
            "source_keyword": "征兵",
            "matched_categories": {"categories": ["咨询"], "confidence": "high"},
            "owner_user_id": "u1",
            "job_id": "job-1",
            "source_platform": "douyin",
        },
        {
            "industry_slug": "test-ind",
            "text": "想咨询报名流程",
            "source_name": "user-a",
            "source_sec_uid": "sec-a",
            "source_short_id": "comment-1",
            "source_video_id": "video-1",
            "source_keyword": "征兵",
            "matched_categories": {"categories": ["咨询"], "confidence": "high"},
            "owner_user_id": "u1",
            "job_id": "job-1",
            "source_platform": "douyin",
        },
    ]

    result = enqueue_tasks_batch_result(comments)

    assert result == {
        "received": 2,
        "valid": 2,
        "inserted": 1,
        "duplicates": 1,
        "invalid": 0,
    }
    rows = db.query(TaskQueue).all()
    assert len(rows) == 1
    assert rows[0].owner_user_id == "u1"
    assert rows[0].job_id == "job-1"
    assert rows[0].platform == "douyin"


def test_video_collected_isolated_by_owner_user_id(db):
    from server.services.task_stats import is_video_collected, mark_video_collected

    mark_video_collected("aweme-shared", "sec-3", owner_user_id="u1")

    assert is_video_collected("aweme-shared", "sec-3", owner_user_id="u1")
    assert not is_video_collected("aweme-shared", "sec-3", owner_user_id="u2")
    # When no owner is supplied the query remains global for backward compatibility.
    assert is_video_collected("aweme-shared", "sec-3")


def test_collector_state_isolated_by_owner_user_id(db):
    from server.services.task_stats import get_collector_state, set_collector_state

    set_collector_state("test-ind", "douyin", "cursor", {"page": 1}, owner_user_id="u1")

    assert get_collector_state("test-ind", "douyin", "cursor", owner_user_id="u1") == {
        "page": 1
    }
    assert (
        get_collector_state("test-ind", "douyin", "cursor", owner_user_id="u2") is None
    )
    # When no owner is supplied the query remains global for backward compatibility.
    assert get_collector_state("test-ind", "douyin", "cursor") == {"page": 1}


def test_video_collected_allows_same_aweme_id_for_different_owners(db):
    from server.services.task_stats import is_video_collected, mark_video_collected

    mark_video_collected("aweme-shared", "sec-3", owner_user_id="u1")
    mark_video_collected("aweme-shared", "sec-4", owner_user_id="u2")

    videos = (
        db.query(CollectedVideo).filter(CollectedVideo.aweme_id == "aweme-shared").all()
    )
    assert len(videos) == 2
    assert is_video_collected("aweme-shared", "sec-3", owner_user_id="u1")
    assert is_video_collected("aweme-shared", "sec-4", owner_user_id="u2")


def test_collector_state_allows_same_key_for_different_owners(db):
    from server.services.task_stats import get_collector_state, set_collector_state

    set_collector_state("test-ind", "douyin", "cursor", {"page": 1}, owner_user_id="u1")
    set_collector_state(
        "test-ind", "douyin", "cursor", {"page": 99}, owner_user_id="u2"
    )

    states = (
        db.query(CollectorState)
        .filter(
            CollectorState.industry_slug == "test-ind",
            CollectorState.platform == "douyin",
            CollectorState.key == "cursor",
        )
        .all()
    )
    assert len(states) == 2
    assert get_collector_state("test-ind", "douyin", "cursor", owner_user_id="u1") == {
        "page": 1
    }
    assert get_collector_state("test-ind", "douyin", "cursor", owner_user_id="u2") == {
        "page": 99
    }


def test_collected_video_owner_user_id_has_index_and_default(db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_bind())
    columns = {col["name"]: col for col in inspector.get_columns("sa_collected_videos")}
    assert "owner_user_id" in columns
    assert (
        columns["owner_user_id"]["default"] is None
        or columns["owner_user_id"]["default"] == "''"
    )

    indexes = {idx["name"]: idx for idx in inspector.get_indexes("sa_collected_videos")}
    assert any("owner_user_id" in idx["column_names"] for idx in indexes.values())


def test_collector_state_owner_user_id_has_index_and_default(db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_bind())
    columns = {col["name"]: col for col in inspector.get_columns("sa_collector_state")}
    assert "owner_user_id" in columns
    assert (
        columns["owner_user_id"]["default"] is None
        or columns["owner_user_id"]["default"] == "''"
    )

    indexes = {idx["name"]: idx for idx in inspector.get_indexes("sa_collector_state")}
    assert any("owner_user_id" in idx["column_names"] for idx in indexes.values())


def test_collected_video_unique_constraint_includes_owner(db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_bind())
    constraints = inspector.get_unique_constraints("sa_collected_videos")
    names = {c["name"] for c in constraints}
    assert "uix_owner_aweme_source" in names
    owner_constraint = next(
        c for c in constraints if c["name"] == "uix_owner_aweme_source"
    )
    assert "owner_user_id" in owner_constraint["column_names"]


def test_collector_state_unique_constraint_includes_owner(db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_bind())
    constraints = inspector.get_unique_constraints("sa_collector_state")
    names = {c["name"] for c in constraints}
    assert "uix_owner_collector_state" in names
    owner_constraint = next(
        c for c in constraints if c["name"] == "uix_owner_collector_state"
    )
    assert "owner_user_id" in owner_constraint["column_names"]


def test_migration_includes_collected_video_and_collector_state_owner_user_id():
    from server.services.migrations import ADDITIVE_MIGRATIONS

    assert "sa_collected_videos" in ADDITIVE_MIGRATIONS
    assert "sa_collector_state" in ADDITIVE_MIGRATIONS
    collected_specs = {
        spec.name: spec for spec in ADDITIVE_MIGRATIONS["sa_collected_videos"]
    }
    collector_specs = {
        spec.name: spec for spec in ADDITIVE_MIGRATIONS["sa_collector_state"]
    }
    assert "owner_user_id" in collected_specs
    assert "owner_user_id" in collector_specs
    assert "VARCHAR(64)" in collected_specs["owner_user_id"].ddl.upper()
    assert "DEFAULT" in collected_specs["owner_user_id"].ddl.upper()


def test_backfill_owner_user_id_for_collected_videos_and_collector_state(db):
    from datetime import datetime, timezone

    from server.models.industry import Industry
    from server.models.task import CollectedVideo, CollectorState, TaskQueue
    from server.services.migrations import _backfill_owner_user_id

    engine = db.get_bind()

    # Create an industry owned by u1 to drive backfill
    db.add(Industry(id="ind-1", user_id="u1", name="Test", slug="test-ind"))
    db.add(
        TaskQueue(
            industry_slug="test-ind",
            video_id="aweme-1",
            comment_id="comment-1",
            owner_user_id="u1",
        )
    )
    # Old rows without owner_user_id (empty string)
    db.add(
        CollectedVideo(
            aweme_id="aweme-1",
            source_sec_uid="sec-1",
            collected_at=datetime.now(timezone.utc).isoformat(),
            owner_user_id="",
        )
    )
    db.add(
        CollectorState(
            industry_slug="test-ind",
            platform="douyin",
            key="cursor",
            value='{"page": 1}',
            owner_user_id="",
        )
    )
    db.commit()

    updated = _backfill_owner_user_id(engine)
    db.expire_all()

    assert any("sa_collected_videos" in item for item in updated)
    assert any("sa_collector_state" in item for item in updated)
    video = (
        db.query(CollectedVideo).filter(CollectedVideo.aweme_id == "aweme-1").first()
    )
    assert video.owner_user_id == "u1"
    state = db.query(CollectorState).filter(CollectorState.key == "cursor").first()
    assert state.owner_user_id == "u1"
