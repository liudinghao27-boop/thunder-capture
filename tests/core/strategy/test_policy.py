from datetime import datetime, timezone
from unittest.mock import patch
from core.config import IndustryConfig
from core.strategy.policy import is_send_window_open


def test_window_open_during_active_hours():
    cfg = IndustryConfig(
        name="测试",
        slug="t",
        keywords=["a"],
        categories=["c"],
        reply_tone="测试",
        reply_style="测试",
        send_start_time="09:00",
        send_end_time="21:00",
    )
    with patch("core.strategy.policy.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 16, 6, 0, tzinfo=timezone.utc)
        assert is_send_window_open(cfg) is True


def test_window_closed_outside_active_hours():
    cfg = IndustryConfig(
        name="测试",
        slug="t",
        keywords=["a"],
        categories=["c"],
        reply_tone="测试",
        reply_style="测试",
        send_start_time="09:00",
        send_end_time="21:00",
    )
    with patch("core.strategy.policy.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 16, 15, 0, tzinfo=timezone.utc)
        assert is_send_window_open(cfg) is False


def test_weekend_paused():
    cfg = IndustryConfig(
        name="测试",
        slug="t",
        keywords=["a"],
        categories=["c"],
        reply_tone="测试",
        reply_style="测试",
        send_start_time="09:00",
        send_end_time="21:00",
        pause_weekends=True,
    )
    with patch("core.strategy.policy.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(
            2026, 6, 13, 6, 0, tzinfo=timezone.utc
        )  # Saturday UTC/China
        assert is_send_window_open(cfg) is False


def test_window_uses_china_business_timezone_by_default():
    cfg = IndustryConfig(
        name="测试",
        slug="t",
        keywords=["a"],
        categories=["c"],
        reply_tone="测试",
        reply_style="测试",
        send_start_time="09:00",
        send_end_time="21:00",
    )
    with patch("core.strategy.policy.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 16, 1, 30, tzinfo=timezone.utc)
        assert is_send_window_open(cfg) is True
