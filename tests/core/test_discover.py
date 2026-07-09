import pytest

from core.config import IndustryConfig


@pytest.mark.asyncio
async def test_run_discovery_collects_keywords_and_target_users(monkeypatch, tmp_path):
    import core.discover as discover

    calls = []

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(
        platform,
        keywords,
        *,
        max_authors=12,
        workspace=None,
        target_users=None,
        **kwargs,
    ):
        calls.append(
            {
                "platform": platform,
                "keywords": list(keywords),
                "target_users": list(target_users or []),
            }
        )
        return [
            {
                "text": f"{platform}-{keywords[0]}",
                "source_sec_uid": "sec-keyword",
                "source_short_id": "c-keyword",
                "source_video_id": "v-keyword",
            },
            {
                "text": "target-user-comment",
                "source_sec_uid": "sec-target",
                "source_short_id": "c-target",
                "source_video_id": "v-target",
                "source_keyword": "target:sec-target",
            },
        ]

    async def fake_run_target_accounts(*args, **kwargs):
        return []

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="测试",
        slug="test-ind",
        keywords=["征兵"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=[" sec-target ", "sec-target", "sec-other"],
    )

    comments = await discover.run_discovery(industry)

    assert calls == [
        {
            "platform": "douyin",
            "keywords": ["征兵"],
            "target_users": ["sec-target", "sec-other"],
        }
    ]
    assert len(comments) == 2
    assert {c["industry_slug"] for c in comments} == {"test-ind"}


@pytest.mark.asyncio
async def test_run_discovery_collects_keyword_and_target_account_sources(
    monkeypatch, tmp_path
):
    import core.discover as discover

    calls = {"keyword": [], "target": []}

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(
        platform,
        keywords,
        *,
        max_authors=12,
        workspace=None,
        target_users=None,
        **kwargs,
    ):
        calls["keyword"].append((platform, list(keywords), list(target_users or [])))
        return [
            {
                "text": "keyword comment",
                "source_sec_uid": "sec-keyword",
                "source_short_id": "comment-keyword",
                "source_video_id": "video-keyword",
                "source_keyword": ",".join(keywords),
            }
        ]

    async def fake_run_target_accounts(
        platform,
        target_users,
        *,
        keywords=None,
        max_videos=None,
        workspace=None,
        **kwargs,
    ):
        calls["target"].append((platform, list(target_users), list(keywords or [])))
        return [
            {
                "text": "target comment",
                "source_sec_uid": "sec-target",
                "source_short_id": "comment-target",
                "source_video_id": "video-target",
                "source_creator": "target-a",
            }
        ]

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["keyword-a"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry)

    assert calls["keyword"] == [("douyin", ["keyword-a"], ["target-a"])]
    assert calls["target"] == [("douyin", ["target-a"], ["keyword-a"])]
    assert [c["source_type"] for c in comments] == ["keyword", "target_account"]
    assert comments[0]["source_keyword"] == "keyword-a"
    assert comments[1]["source_keyword"] == "target:target-a"
    assert comments[1]["source_creator"] == "target-a"
    assert {c["industry_slug"] for c in comments} == {"test-ind"}


@pytest.mark.asyncio
async def test_run_discovery_dedupes_same_comment_and_prefers_target_source(
    monkeypatch, tmp_path
):
    import core.discover as discover

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    duplicate = {
        "text": "same comment",
        "source_sec_uid": "sec-1",
        "source_short_id": "comment-1",
        "source_video_id": "video-1",
    }

    async def fake_run_platform(*args, **kwargs):
        return [dict(duplicate, source_keyword="keyword-a")]

    async def fake_run_target_accounts(*args, **kwargs):
        return [dict(duplicate, source_creator="target-a")]

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["keyword-a"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry)

    assert len(comments) == 1
    assert comments[0]["source_type"] == "target_account"
    assert comments[0]["source_keyword"] == "target:target-a"
    assert comments[0]["source_creator"] == "target-a"


@pytest.mark.asyncio
async def test_run_discovery_stops_before_target_collection_when_cancelled(
    monkeypatch, tmp_path
):
    import core.discover as discover

    calls = {"target": 0}
    stop_checks = {"count": 0}

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(*args, **kwargs):
        return [
            {
                "text": "keyword comment",
                "source_sec_uid": "sec-keyword",
                "source_short_id": "comment-keyword",
                "source_video_id": "video-keyword",
                "source_keyword": "keyword-a",
            }
        ]

    async def fake_run_target_accounts(*args, **kwargs):
        calls["target"] += 1
        return []

    def should_stop():
        stop_checks["count"] += 1
        return stop_checks["count"] >= 2

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["keyword-a"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry, should_stop=should_stop)

    assert calls["target"] == 0
    assert len(comments) == 1
    assert comments[0]["source_type"] == "keyword"


@pytest.mark.asyncio
async def test_run_discovery_stops_before_appending_target_results_when_cancelled(
    monkeypatch, tmp_path
):
    import core.discover as discover

    stop_checks = {"count": 0}

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(*args, **kwargs):
        return [
            {
                "text": "keyword comment",
                "source_sec_uid": "sec-keyword",
                "source_short_id": "comment-keyword",
                "source_video_id": "video-keyword",
                "source_keyword": "keyword-a",
            }
        ]

    async def fake_run_target_accounts(*args, **kwargs):
        return [
            {
                "text": "target comment",
                "source_sec_uid": "sec-target",
                "source_short_id": "comment-target",
                "source_video_id": "video-target",
                "source_creator": "target-a",
            }
        ]

    def should_stop():
        stop_checks["count"] += 1
        return stop_checks["count"] >= 3

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["keyword-a"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry, should_stop=should_stop)

    assert len(comments) == 1
    assert comments[0]["source_type"] == "keyword"
    assert comments[0]["source_keyword"] == "keyword-a"


@pytest.mark.asyncio
async def test_run_discovery_collects_target_accounts_without_keywords(
    monkeypatch, tmp_path
):
    import core.discover as discover

    calls = {"keyword": 0, "target": []}

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(*args, **kwargs):
        calls["keyword"] += 1
        return []

    async def fake_run_target_accounts(
        platform,
        target_users,
        *,
        keywords=None,
        max_videos=None,
        workspace=None,
        **kwargs,
    ):
        calls["target"].append((platform, list(target_users), list(keywords or [])))
        return [
            {
                "text": "target comment",
                "source_sec_uid": "sec-target",
                "source_short_id": "comment-target",
                "source_video_id": "video-target",
                "source_creator": "target-a",
            }
        ]

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=[],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        target_users=["target-a"],
    )

    comments = await discover.run_discovery(industry)

    assert calls["keyword"] == 0
    assert calls["target"] == [("douyin", ["target-a"], [])]
    assert len(comments) == 1
    assert comments[0]["source_type"] == "target_account"
    assert comments[0]["source_keyword"] == "target:target-a"
    assert comments[0]["source_creator"] == "target-a"


@pytest.mark.asyncio
async def test_run_discovery_batches_keywords_and_continues_after_timeout(
    monkeypatch, tmp_path
):
    import core.discover as discover

    calls = []

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(
        platform,
        keywords,
        *,
        max_authors=12,
        workspace=None,
        target_users=None,
        **kwargs,
    ):
        batch = list(keywords)
        calls.append(batch)
        if batch == ["kw1", "kw2"]:
            raise TimeoutError("MediaCrawler douyin timed out after 90s")
        return [
            {
                "text": f"comment-{batch[0]}",
                "source_sec_uid": f"sec-{batch[0]}",
                "source_short_id": f"comment-{batch[0]}",
                "source_video_id": f"video-{batch[0]}",
                "source_keyword": ",".join(batch),
            }
        ]

    async def fake_run_target_accounts(*args, **kwargs):
        return []

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["kw1", "kw2", "kw3", "kw4", "kw5"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        keyword_batch_size=2,
    )

    comments = await discover.run_discovery(industry)

    assert calls == [["kw1", "kw2"], ["kw3", "kw4"], ["kw5"]]
    assert [c["source_keyword"] for c in comments] == ["kw3,kw4", "kw5"]
    assert {c["industry_slug"] for c in comments} == {"test-ind"}


@pytest.mark.asyncio
async def test_run_discovery_stops_keyword_batches_after_reaching_collect_target(
    monkeypatch, tmp_path
):
    import core.discover as discover

    calls = []

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(
        platform,
        keywords,
        *,
        max_authors=12,
        workspace=None,
        target_users=None,
        **kwargs,
    ):
        batch = list(keywords)
        calls.append(batch)
        return [
            {
                "text": f"comment-{batch[0]}-{idx}",
                "source_sec_uid": f"sec-{batch[0]}-{idx}",
                "source_short_id": f"comment-{batch[0]}-{idx}",
                "source_video_id": f"video-{batch[0]}-{idx}",
                "source_keyword": ",".join(batch),
            }
            for idx in range(3)
        ]

    async def fake_run_target_accounts(*args, **kwargs):
        return []

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["kw1", "kw2", "kw3", "kw4", "kw5", "kw6"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        keyword_batch_size=2,
        collect_authors_per_run=3,
    )

    comments = await discover.run_discovery(industry)

    assert calls == [["kw1", "kw2"]]
    assert len(comments) == 3
    assert {c["industry_slug"] for c in comments} == {"test-ind"}


@pytest.mark.asyncio
async def test_run_discovery_caps_large_keyword_batch_size_for_mediacrawler(
    monkeypatch, tmp_path
):
    import core.discover as discover

    calls = []

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(
        platform,
        keywords,
        *,
        max_authors=12,
        workspace=None,
        target_users=None,
        **kwargs,
    ):
        calls.append(list(keywords))
        return []

    async def fake_run_target_accounts(*args, **kwargs):
        return []

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=["kw1", "kw2", "kw3", "kw4", "kw5", "kw6", "kw7"],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        keyword_batch_size=12,
    )

    await discover.run_discovery(industry)

    assert calls == [["kw1", "kw2", "kw3"], ["kw4", "kw5", "kw6"], ["kw7"]]


@pytest.mark.asyncio
async def test_run_discovery_splits_space_joined_keyword_groups(monkeypatch, tmp_path):
    import core.discover as discover

    calls = []

    class FakeBrowser:
        port = 9222

        def __init__(self, user_data_dir):
            self.user_data_dir = user_data_dir

        def start(self):
            return None

        def close(self):
            return None

    async def fake_run_platform(
        platform,
        keywords,
        *,
        max_authors=12,
        workspace=None,
        target_users=None,
        **kwargs,
    ):
        calls.append(list(keywords))
        return []

    async def fake_run_target_accounts(*args, **kwargs):
        return []

    monkeypatch.setattr(discover, "prepare_mediacrawler_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        discover, "configure_mediacrawler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(discover, "ShadowBrowser", FakeBrowser)
    monkeypatch.setattr(discover, "run_platform", fake_run_platform)
    monkeypatch.setattr(discover, "run_target_accounts", fake_run_target_accounts)
    monkeypatch.setattr(discover.shutil, "rmtree", lambda *args, **kwargs: None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "base_config.py").write_text("", encoding="utf-8")

    industry = IndustryConfig(
        name="Test",
        slug="test-ind",
        keywords=[
            "贷款 征信 利息 还款方式 贷款年限",
            "贷款 征信 利息 还款方式 贷款年限怎么学",
        ],
        reply_tone="",
        reply_style="",
        categories=[],
        platforms=["douyin"],
        keyword_batch_size=12,
    )

    await discover.run_discovery(industry)

    flattened = [keyword for batch in calls for keyword in batch]
    assert "贷款 征信 利息 还款方式 贷款年限" not in flattened
    assert "贷款" in flattened
    assert "征信" in flattened
    assert "还款方式" in flattened
    assert all(len(batch) <= 3 for batch in calls)
