"""Tests for core.classify bug fixes."""

import json
from unittest.mock import patch


from core.classify import enqueue_classified


def test_enqueue_classified_passes_string_matched_categories_without_double_encoding():
    """If comment already has matched_categories as JSON string, pass it as-is."""
    captured = {}

    def fake_enqueue_tasks_batch(comments):
        captured["comments"] = comments
        return len(comments)

    with patch("core.classify.enqueue_tasks_batch", fake_enqueue_tasks_batch):
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

    assert "comments" in captured
    assert len(captured["comments"]) == 1
    matched = captured["comments"][0]["matched_categories"]
    assert isinstance(matched, str)
    parsed = json.loads(matched)
    assert parsed["categories"] == ["咨询类"]
    assert parsed["confidence"] == "high"


def test_enqueue_classified_encodes_dict_matched_categories():
    """If comment has matched_categories as dict, json.dumps it."""
    captured = {}

    def fake_enqueue_tasks_batch(comments):
        captured["comments"] = comments
        return len(comments)

    with patch("core.classify.enqueue_tasks_batch", fake_enqueue_tasks_batch):
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

    assert "comments" in captured
    assert len(captured["comments"]) == 1
    matched = captured["comments"][0]["matched_categories"]
    assert isinstance(matched, str)
    parsed = json.loads(matched)
    assert parsed["categories"] == ["意向类"]
    assert parsed["confidence"] == "medium"
