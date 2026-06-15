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
    mock_post.assert_called_once()


@patch("server.services.webhook.httpx.post")
def test_push_leads_failure(mock_post):
    mock_post.side_effect = Exception("connection error")
    result = push_leads_to_webhook(
        webhook_url="https://example.com/hook",
        industry_slug="recruitment",
        industry_name="征兵咨询",
        leads=[{"id": 1}],
    )
    assert result["ok"] is False
    assert "connection error" in result["error"]
