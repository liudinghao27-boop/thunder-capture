from unittest.mock import patch, MagicMock
from server.services.webhook import push_leads_to_webhook, WebhookPayload


def test_webhook_payload_building():
    payload = WebhookPayload(
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1, "user_name": "u1"}],
    )
    data = payload.to_dict()
    assert data["industry_slug"] == "recruitment"
    assert data["event"] == "leads.available"
    assert data["sent_at"] is not None
    assert len(data["leads"]) == 1


@patch("server.services.webhook.httpx.post")
def test_push_leads_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    mock_post.return_value = mock_resp

    result = push_leads_to_webhook(
        webhook_url="https://example.com/hook",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1, "user_name": "u1"}],
    )
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["response_preview"] == "ok"
    assert result["error"] == ""
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.kwargs["headers"]["Content-Type"] == "application/json"
    assert "recruitment" in call_args.kwargs["content"]


@patch("server.services.webhook.httpx.post")
def test_push_leads_non_2xx(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "server error"
    mock_post.return_value = mock_resp

    result = push_leads_to_webhook(
        webhook_url="https://example.com/hook",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1}],
    )
    assert result["ok"] is False
    assert result["status_code"] == 500
    assert "server error" in result["response_preview"]


@patch("server.services.webhook.httpx.post")
def test_push_leads_empty_url(mock_post):
    result = push_leads_to_webhook(
        webhook_url="",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1}],
    )
    assert result["ok"] is False
    assert result["error"] == "webhook_url empty"
    mock_post.assert_not_called()


@patch("server.services.webhook.httpx.post")
def test_push_leads_network_failure(mock_post):
    import httpx

    mock_post.side_effect = httpx.ConnectError("connection error")
    result = push_leads_to_webhook(
        webhook_url="https://example.com/hook",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1}],
    )
    assert result["ok"] is False
    assert "connection error" in result["error"]


@patch("server.services.webhook.httpx.post")
@patch("server.services.webhook.is_safe_webhook_url")
def test_push_leads_rejects_unsafe_url(mock_safe, mock_post):
    mock_safe.return_value = False
    result = push_leads_to_webhook(
        webhook_url="https://10.0.0.1/hook",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1}],
    )
    assert result["ok"] is False
    assert result["status_code"] is None
    assert "不安全" in result["error"]
    mock_post.assert_not_called()


def test_push_leads_response_preview_truncation():
    long_text = "x" * 1000
    with patch("server.services.webhook.httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = long_text
        mock_post.return_value = mock_resp
        result = push_leads_to_webhook(
            webhook_url="https://example.com/hook",
            industry_slug="recruitment",
            industry_name="征兵咨询",
            leads=[{"id": 1}],
        )
    assert result["response_preview"] == long_text[:500]
