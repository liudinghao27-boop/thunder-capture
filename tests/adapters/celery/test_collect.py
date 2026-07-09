"""Tests for adapters.celery.collect bug fixes."""

from unittest.mock import patch

from adapters.celery.collect import run_mediacrawler


def test_run_mediacrawler_calls_runner_and_returns_count():
    """run_mediacrawler should delegate to adapters.mediacrawler.runner.run_platform."""
    fake_comments = [{"text": "hello"}, {"text": "world"}]

    with patch(
        "adapters.mediacrawler.runner.run_platform",
        return_value=fake_comments,
    ) as mock_run:
        result = run_mediacrawler.run("douyin", ["征兵"], "recruitment")

    mock_run.assert_called_once_with("douyin", ["征兵"])
    assert result["platform"] == "douyin"
    assert result["industry_slug"] == "recruitment"
    assert result["status"] == "collected"
    assert result["count"] == 2


def test_run_mediacrawler_returns_zero_on_empty_result():
    """When runner returns no comments, count should be 0."""
    with patch(
        "adapters.mediacrawler.runner.run_platform", return_value=[]
    ) as mock_run:
        result = run_mediacrawler.run("douyin", ["none"], "recruitment")

    mock_run.assert_called_once_with("douyin", ["none"])
    assert result["count"] == 0
