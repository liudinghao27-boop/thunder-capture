"""Tests for MediaCrawler runner isolation."""

import re
from pathlib import Path

import pytest

from adapters.mediacrawler.runner import (
    configure_mediacrawler,
    prepare_mediacrawler_workspace,
)


@pytest.fixture
def workspace(tmp_path):
    """Provide an isolated MediaCrawler workspace for a single test."""
    ws = prepare_mediacrawler_workspace()
    yield ws
    import shutil

    shutil.rmtree(ws, ignore_errors=True)


def _read_base_config_value(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"{name}\s*=\s*(.+)", text)
    assert match, f"{name} not found in {path}"
    return match.group(1).split("#", 1)[0].strip()


def test_configure_mediacrawler_updates_isolated_config(workspace):
    base_config = workspace / "config" / "base_config.py"
    configure_mediacrawler(base_config, cdp_port=12345, max_comments=42)

    assert _read_base_config_value(base_config, "SAVE_DATA_OPTION") == '"jsonl"'
    assert _read_base_config_value(base_config, "ENABLE_GET_COMMENTS") == "True"
    assert _read_base_config_value(base_config, "ENABLE_CDP_MODE") == "True"
    assert _read_base_config_value(base_config, "CDP_DEBUG_PORT") == "12345"
    assert _read_base_config_value(base_config, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES") == "42"


def test_workspace_keeps_runtime_cache_package(workspace):
    """MediaCrawler proxy modules import cache.abs_cache at runtime."""
    assert (workspace / "cache" / "abs_cache.py").exists()


def test_concurrent_config_isolation():
    """Two workspaces configured with different settings must stay independent."""
    ws1 = prepare_mediacrawler_workspace()
    ws2 = prepare_mediacrawler_workspace()
    try:
        cfg1 = ws1 / "config" / "base_config.py"
        cfg2 = ws2 / "config" / "base_config.py"
        configure_mediacrawler(cfg1, cdp_port=11111, max_comments=10)
        configure_mediacrawler(cfg2, cdp_port=22222, max_comments=20)

        assert _read_base_config_value(cfg1, "CDP_DEBUG_PORT") == "11111"
        assert _read_base_config_value(cfg1, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES") == "10"
        assert _read_base_config_value(cfg2, "CDP_DEBUG_PORT") == "22222"
        assert _read_base_config_value(cfg2, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES") == "20"
    finally:
        import shutil

        shutil.rmtree(ws1, ignore_errors=True)
        shutil.rmtree(ws2, ignore_errors=True)


def test_shared_base_config_not_mutated_by_workspace_configure(workspace, tmp_path):
    """Configuring an isolated workspace must not touch the shared base_config.py."""
    shared = (
        Path(__file__).resolve().parent.parent.parent
        / "deps"
        / "MediaCrawler"
        / "config"
        / "base_config.py"
    )
    before = shared.read_text(encoding="utf-8")

    isolated = workspace / "config" / "base_config.py"
    configure_mediacrawler(isolated, cdp_port=99999, max_comments=99)

    after = shared.read_text(encoding="utf-8")
    assert before == after


@pytest.mark.asyncio
async def test_run_target_accounts_unsupported_platform_returns_empty(tmp_path, caplog):
    from adapters.mediacrawler.runner import run_target_accounts

    caplog.set_level("INFO")
    result = await run_target_accounts(
        "unknown",
        ["target-a", " target-b ", "target-a"],
        keywords=["征兵"],
        max_videos=3,
        workspace=tmp_path,
    )

    assert result == []
    assert "target account collection unsupported" in caplog.text


@pytest.mark.asyncio
async def test_run_target_accounts_uses_creator_mode_and_parses_comments(tmp_path, monkeypatch):
    from adapters.mediacrawler import runner
    import json
    import sys

    data_dir = tmp_path / "data" / "douyin" / "jsonl"
    data_dir.mkdir(parents=True)
    output = data_dir / "creator_comments_2026-07-03.jsonl"
    output.write_text(
        json.dumps(
            {
                "content": "想了解报考条件",
                "nickname": "lead-user",
                "sec_uid": "sec-1",
                "comment_id": "comment-1",
                "aweme_id": "video-1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return FakeProcess()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await runner.run_target_accounts(
        "douyin",
        ["MS4w-target", " MS4w-target "],
        keywords=["征兵"],
        max_videos=7,
        workspace=tmp_path,
    )

    assert captured["cmd"][0] == sys.executable
    assert "--type" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--type") + 1] == "creator"
    assert "--creator_id" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--creator_id") + 1] == "MS4w-target"
    assert "--crawler_max_notes_count" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--crawler_max_notes_count") + 1] == "7"
    assert captured["cwd"] == str(tmp_path)
    assert result == [
        {
            "text": "想了解报考条件",
            "source_name": "lead-user",
            "source_sec_uid": "sec-1",
            "source_short_id": "comment-1",
            "source_video_id": "video-1",
            "source_keyword": "target:MS4w-target",
            "source_platform": "douyin",
            "source_creator": "MS4w-target",
        }
    ]
    assert not output.exists()


@pytest.mark.asyncio
async def test_run_platform_uses_current_python_interpreter(tmp_path, monkeypatch):
    from adapters.mediacrawler import runner
    import sys

    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return FakeProcess()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await runner.run_platform("douyin", ["keyword"], workspace=tmp_path)

    assert result == []
    assert captured["cmd"][0] == sys.executable
    assert captured["cmd"][1:4] == ("main.py", "--platform", "dy")


@pytest.mark.asyncio
async def test_run_platform_logs_subprocess_output_when_no_jsonl(tmp_path, monkeypatch, caplog):
    from adapters.mediacrawler import runner

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return "search returned empty".encode("utf-8"), "login required".encode("utf-8")

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    caplog.set_level("WARNING", logger="thunder.mediacrawler")

    result = await runner.run_platform("douyin", ["keyword"], workspace=tmp_path)

    assert result == []
    assert "No JSONL output" in caplog.text
    assert "search returned empty" in caplog.text
    assert "login required" in caplog.text
