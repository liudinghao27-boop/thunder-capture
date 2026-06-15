from fastapi.testclient import TestClient
from server.main import app
from server.auth import get_current_user

client = TestClient(app)


def test_export_csv_requires_auth():
    resp = client.post("/api/leads/export", json={"industry_slug": "recruitment", "format": "csv"})
    assert resp.status_code in (401, 403)


def test_export_csv_returns_file(monkeypatch):
    from server.models.task import TaskQueue
    import server.models as models_module

    class FakeUser:
        id = "user-1"

    app.dependency_overrides[get_current_user] = lambda: FakeUser()

    class FakeRow:
        id = 1
        platform = "douyin"
        keyword = "当兵"
        source_creator = "兵爸"
        source_video_desc = ""
        user_name = "u1"
        unique_id = "uid1"
        short_id = ""
        douyin_id = ""
        text = "我想当兵"
        matched_categories = "[]"
        ai_reply = ""
        status = "pending"
        error = ""
        fetched_at = "2026-06-15T10:00:00"
        processed_at = ""

        def __getattr__(self, name):
            return ""

    class FakeQuery:
        def filter(self, *a, **k): return self
        def count(self): return 1
        def order_by(self, *a): return self
        def limit(self, n): return self
        def offset(self, n): return self
        def all(self): return [FakeRow()]

    class FakeSession:
        def query(self, model): return FakeQuery()
        def close(self): pass

    monkeypatch.setattr(models_module, "SessionLocal", FakeSession)

    try:
        resp = client.post("/api/leads/export", json={"industry_slug": "recruitment", "format": "csv"})
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "我想当兵" in resp.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
