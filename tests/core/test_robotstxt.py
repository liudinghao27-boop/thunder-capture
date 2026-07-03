from core import robotstxt


def test_check_robots_denies_when_fetch_fails(monkeypatch):
    robotstxt.clear_cache()

    monkeypatch.setattr(robotstxt, "_fetch_robots_txt", lambda domain: None)

    result = robotstxt.check_robots("example.com", "/any")

    assert result["allowed"] is False
    assert result["fetch_error"] is True


def test_check_robots_cache_expires(monkeypatch):
    robotstxt.clear_cache()
    calls = {"count": 0}

    def fake_fetch(domain):
        calls["count"] += 1
        return "User-agent: *\nDisallow: /private\n"

    monkeypatch.setattr(robotstxt, "_fetch_robots_txt", fake_fetch)
    monkeypatch.setattr(robotstxt, "_ROBOTS_CACHE_TTL_SECONDS", 0)

    assert robotstxt.check_robots("example.com", "/public")["allowed"] is True
    assert robotstxt.check_robots("example.com", "/public")["allowed"] is True
    assert calls["count"] == 2
