from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_mark_replied_requires_auth():
    resp = client.post("/api/leads/1/mark-replied", json={"reply_text": "hi"})
    assert resp.status_code in (401, 403)


def test_mark_converted_requires_auth():
    resp = client.post("/api/leads/1/mark-converted", json={"conversion_value": "100"})
    assert resp.status_code in (401, 403)
