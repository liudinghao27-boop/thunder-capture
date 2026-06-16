"""Tests for core.classify bug fixes."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.classify import enqueue_classified


def test_enqueue_classified_passes_string_matched_categories_without_double_encoding():
    """If comment already has matched_categories as JSON string, pass it as-is."""
    captured = {}

    def fake_enqueue_task(*, matched_categories, **kwargs):
        captured["matched_categories"] = matched_categories

    with patch("server.services.task_stats.enqueue_task", fake_enqueue_task):
        comment = {
            "industry_slug": "test-ind",
            "text": "hello",
            "source_name": "user",
            "source_sec_uid": "sec1",
            "source_short_id": "short1",
            "source_video_id": "vid1",
            "source_keyword": "kw",
            "matched_categories": json.dumps({"categories": ["咨询类"], "confidence": "high"}, ensure_ascii=False),
        }
        enqueue_classified([comment])

    assert isinstance(captured["matched_categories"], str)
    parsed = json.loads(captured["matched_categories"])
    assert parsed["categories"] == ["咨询类"]
    assert parsed["confidence"] == "high"


def test_enqueue_classified_encodes_dict_matched_categories():
    """If comment has matched_categories as dict, json.dumps it."""
    captured = {}

    def fake_enqueue_task(*, matched_categories, **kwargs):
        captured["matched_categories"] = matched_categories

    with patch("server.services.task_stats.enqueue_task", fake_enqueue_task):
        comment = {
            "industry_slug": "test-ind",
            "text": "hello",
            "source_name": "user",
            "source_sec_uid": "sec1",
            "source_short_id": "short1",
            "source_video_id": "vid1",
            "source_keyword": "kw",
            "matched_categories": {"categories": ["意向类"], "confidence": "medium"},
        }
        enqueue_classified([comment])

    assert isinstance(captured["matched_categories"], str)
    parsed = json.loads(captured["matched_categories"])
    assert parsed["categories"] == ["意向类"]
    assert parsed["confidence"] == "medium"
