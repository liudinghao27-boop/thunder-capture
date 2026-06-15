from unittest.mock import patch, MagicMock
from core.task.worker import run_senders
from core.config import IndustryConfig


def test_run_senders_without_compliance_still_attempts_devices():
    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["a"],
        categories=["c"],
        reply_tone="测试",
        reply_style="测试",
        compliance_mode=False,
    )
    with patch("core.task.worker.load_active_devices") as mock_load:
        mock_load.return_value = []
        result = run_senders(industry, device_ids=[])
        assert result["ok"] is False
        assert result.get("skipped") is not True
        mock_load.assert_called_once()


def test_compliance_mode_no_device_scheduling():
    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["a"],
        categories=["c"],
        reply_tone="测试",
        reply_style="测试",
        compliance_mode=True,
    )
    with patch("core.task.worker.load_active_devices") as mock_load:
        result = run_senders(industry, device_ids=[])
        assert result["ok"] is True
        assert result.get("skipped") is True
        mock_load.assert_not_called()


def test_run_senders_skips_when_compliance_mode_enabled():
    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["a"],
        reply_tone="测试",
        reply_style="测试",
        categories=["c"],
        compliance_mode=True,
    )
    result = run_senders(industry, device_ids=[])
    assert result["ok"] is True
    assert result.get("skipped") is True
    assert "compliance_mode" in result["reason"]


def test_run_senders_runs_normally_without_compliance_mode():
    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["a"],
        reply_tone="测试",
        reply_style="测试",
        categories=["c"],
        compliance_mode=False,
    )
    with patch("core.task.worker.load_active_devices") as mock_load:
        mock_load.return_value = []
        result = run_senders(industry, device_ids=[])
        assert result["ok"] is False
        assert result.get("error") == "no available devices"
