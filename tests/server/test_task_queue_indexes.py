"""Tests for server.models.task composite index fixes."""

from sqlalchemy import Index

from server.models.task import TaskQueue


def test_task_queue_has_composite_indexes():
    """TaskQueue should have composite indexes for common query patterns."""
    table_args = TaskQueue.__table_args__
    indexes = [arg for arg in table_args if isinstance(arg, Index)]
    index_names = {idx.name for idx in indexes}
    assert "ix_task_queue_industry_status" in index_names
    assert "ix_task_queue_industry_status_owner" in index_names
    assert "ix_task_queue_fetched_at" in index_names


def test_task_queue_has_unique_constraint():
    """Original unique constraint on comment_id + video_id should remain."""
    from sqlalchemy import UniqueConstraint

    table_args = TaskQueue.__table_args__
    constraints = [arg for arg in table_args if isinstance(arg, UniqueConstraint)]
    assert len(constraints) == 1
    assert constraints[0].name == "uix_comment_video"
