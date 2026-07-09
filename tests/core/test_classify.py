"""Tests for core.classify bug fixes."""

import json
from unittest.mock import patch


from core.classify import DirectLLMBackend, enqueue_classified
from core.config import IndustryConfig


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
            "matched_categories": json.dumps(
                {"categories": ["咨询类"], "confidence": "high"}, ensure_ascii=False
            ),
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


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return _FakeResponse(
            json.dumps(
                [
                    {
                        "index": 0,
                        "is_target": True,
                        "confidence": "high",
                        "category": "consult",
                        "question": f"batch-{self.calls}",
                        "suggested_reply_topic": "reply",
                        "evidence": "explicit question",
                    }
                ],
                ensure_ascii=False,
            )
        )


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeLLMClient:
    def __init__(self):
        self.chat = _FakeChat()


def test_direct_llm_backend_offsets_batch_local_indexes_to_global_indexes():
    backend = DirectLLMBackend(llm_client=_FakeLLMClient())
    candidates = [{"text": f"candidate {idx} 怎么办理"} for idx in range(11)]
    industry = IndustryConfig(
        name="Test",
        slug="test",
        keywords=[],
        reply_tone="",
        reply_style="",
        categories=["consult"],
    )

    results = backend.classify(candidates, industry, ["consult"])

    assert [item.index for item in results] == [0, 10]
    assert [item.question for item in results] == ["batch-1", "batch-2"]
