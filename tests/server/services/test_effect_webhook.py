"""Tests for effect webhook service SSRF hardening."""

from unittest.mock import patch, MagicMock

from server.services.effect_webhook import push_effect_event


@patch("server.services.effect_webhook.httpx.post")
def test_push_effect_event_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    mock_post.return_value = mock_resp

    result = push_effect_event(
        event="lead.replied",
        industry_slug="recruitment",
        lead={"id": 1, "reply_text": "hello"},
        webhook_url="https://example.com/hook",
    )
    assert result["ok"] is True
    assert result["status_code"] == 200
    mock_post.assert_called_once()


@patch("server.services.effect_webhook.httpx.post")
@patch("server.services.effect_webhook.is_safe_webhook_url")
def test_push_effect_event_rejects_unsafe_url(mock_safe, mock_post):
    mock_safe.return_value = False
    result = push_effect_event(
        event="lead.replied",
        industry_slug="recruitment",
        lead={"id": 1},
        webhook_url="https://192.168.1.1/hook",
    )
    assert result["ok"] is False
    assert "不安全" in result["error"]
    mock_post.assert_not_called()
