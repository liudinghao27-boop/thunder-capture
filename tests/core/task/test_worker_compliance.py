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
        send_start_time="00:00",
        send_end_time="23:59",
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


def test_run_senders_includes_scheduler_limits_in_celery_task_data(monkeypatch):
    from unittest.mock import MagicMock

    industry = _make_industry(compliance_mode=False)
    industry.daily_send_max = 25
    industry.global_daily_limit = 500

    class FakeDevice:
        def __init__(self):
            self.id = "dev-1"

        def as_sender_dict(self):
            return {"id": "dev-1", "adb_serial": "", "daily_limit": 15, "min_interval_sec": 90}

    with patch("core.task.worker.load_active_devices", return_value=[FakeDevice()]):
        with patch("core.task.worker.is_send_window_open", return_value=True):
            mock_send = MagicMock()
            mock_send.delay.return_value = MagicMock(id="celery-id-1")
            monkeypatch.setattr("adapters.celery.send.send_dm_task", mock_send)

            run_senders(industry, device_ids=[])

    assert mock_send.delay.called
    _, kwargs = mock_send.delay.call_args
    task_data = kwargs["task_data"]
    assert task_data.get("daily_send_max") == 25
    assert task_data.get("global_daily_limit") == 500
