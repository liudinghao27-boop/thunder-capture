from unittest.mock import patch

from core.config import IndustryConfig
from core.task.worker import run_senders


def _make_industry(compliance_mode: bool = False) -> IndustryConfig:
    return IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["a"],
        categories=["c"],
        reply_tone="测试",
        reply_style="测试",
        compliance_mode=compliance_mode,
    )


def test_run_senders_skips_when_compliance_mode_enabled():
    industry = _make_industry(compliance_mode=True)
    with patch("core.task.worker.load_active_devices") as mock_load:
        result = run_senders(industry, device_ids=[])
        assert result["ok"] is True
        assert result.get("skipped") is True
        assert "compliance_mode" in result["reason"]
        mock_load.assert_not_called()


def test_run_senders_runs_normally_without_compliance_mode():
    industry = _make_industry(compliance_mode=False)
    with patch("core.task.worker.load_active_devices") as mock_load:
        mock_load.return_value = []
        result = run_senders(industry, device_ids=[])
        assert result["ok"] is False
        assert result.get("error") == "no available devices"
        assert result.get("skipped") is not True
        mock_load.assert_called_once()
