"""Tests for adapters.celery.classify bug fixes."""

from unittest.mock import MagicMock, patch

from adapters.celery.classify import classify_batch_task


def test_classify_batch_task_uses_client_classify_not_classify_batch():
    """DifyClient only has classify(); task must not call the non-existent classify_batch."""
    mock_client = MagicMock()
    mock_client.available = True
    mock_client.classify.return_value = []

    with patch("adapters.dify.client.DifyClient", return_value=mock_client):
        comments = [{"text": "怎么报名"}]
        classify_batch_task.run(comments, "征兵咨询", ["咨询类"])

    mock_client.classify.assert_called_once()
    assert not mock_client.classify_batch.called


def test_classify_batch_task_builds_industry_config_with_required_fields():
    """IndustryConfig requires reply_tone, reply_style, reply_hook."""
    mock_client = MagicMock()
    mock_client.available = False

    captured = {}

    def fake_classify_batch(comments, industry):
        captured["industry"] = industry
        return []

    with patch("adapters.dify.client.DifyClient", return_value=mock_client):
        with patch("core.classify.classify_batch", fake_classify_batch):
            classify_batch_task.run([{"text": "test"}], "Test Industry", ["咨询类"])

    assert captured["industry"].reply_tone == "业内人士"
    assert captured["industry"].reply_style == "亲切专业"
    assert captured["industry"].reply_hook == ""
