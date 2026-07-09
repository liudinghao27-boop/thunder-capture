"""Tests for MediaCrawler runner isolation."""

import re
import asyncio
from pathlib import Path

import pytest

from adapters.mediacrawler.runner import (
    MediaCrawlerProcessError,
    MediaCrawlerTimeoutError,
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
    assert (
        _read_base_config_value(base_config, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES")
        == "42"
    )


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
        assert (
            _read_base_config_value(cfg1, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES")
            == "10"
        )
        assert _read_base_config_value(cfg2, "CDP_DEBUG_PORT") == "22222"
        assert (
            _read_base_config_value(cfg2, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES")
            == "20"
        )
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
async def test_run_target_accounts_uses_creator_mode_and_parses_comments(
    tmp_path, monkeypatch
):
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

    monkeypatch.setattr(
        runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

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
    assert (
        captured["cmd"][captured["cmd"].index("--crawler_max_notes_count") + 1] == "7"
    )
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
async def test_run_target_accounts_filters_invalid_audience_descriptions(
    tmp_path, monkeypatch, caplog
):
    from adapters.mediacrawler import runner

    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(
        runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )
    caplog.set_level("WARNING", logger="thunder.mediacrawler")

    result = await runner.run_target_accounts(
        "douyin",
        ["关注征兵的人", "MS4w-valid", "咨询课程的人"],
        workspace=tmp_path,
    )

    assert result == []
    assert captured["cmd"][captured["cmd"].index("--creator_id") + 1] == "MS4w-valid"
    assert "Ignored invalid target account identifiers" in caplog.text


@pytest.mark.asyncio
async def test_run_target_accounts_skips_when_all_targets_are_invalid(
    tmp_path, monkeypatch, caplog
):
    from adapters.mediacrawler import runner

    called = False

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess should not start for invalid target ids")

    monkeypatch.setattr(
        runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )
    caplog.set_level("WARNING", logger="thunder.mediacrawler")

    result = await runner.run_target_accounts(
        "douyin",
        ["关注征兵的人", "咨询课程的人"],
        workspace=tmp_path,
    )

    assert result == []
    assert called is False
    assert "No valid target account identifiers" in caplog.text


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

    monkeypatch.setattr(
        runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    result = await runner.run_platform("douyin", ["keyword"], workspace=tmp_path)

    assert result == []
    assert captured["cmd"][0] == sys.executable
    assert captured["cmd"][1:4] == ("main.py", "--platform", "dy")


@pytest.mark.asyncio
async def test_run_platform_logs_subprocess_output_when_no_jsonl(
    tmp_path, monkeypatch, caplog
):
    from adapters.mediacrawler import runner

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return "search returned empty".encode("utf-8"), "login required".encode(
                "utf-8"
            )

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )
    caplog.set_level("WARNING", logger="thunder.mediacrawler")

    result = await runner.run_platform("douyin", ["keyword"], workspace=tmp_path)

    assert result == []
    assert "No JSONL output" in caplog.text
    assert "search returned empty" in caplog.text
    assert "login required" in caplog.text


@pytest.mark.asyncio
async def test_mediacrawler_process_timeout_kills_hung_subprocess(
    tmp_path, monkeypatch
):
    from adapters.mediacrawler import runner

    class FakeProcess:
        returncode = None
        killed = False

        async def communicate(self):
            await asyncio.sleep(10)
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    fake_process = FakeProcess()

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_process

    monkeypatch.setattr(
        runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    with pytest.raises(TimeoutError, match="timed out"):
        await runner._run_mediacrawler_process(
            ["python", "main.py"],
            mc_dir=tmp_path,
            platform="douyin",
            timeout_seconds=0.01,
        )

    assert fake_process.killed is True


@pytest.mark.asyncio
async def test_run_platform_salvages_jsonl_when_subprocess_fails(
    tmp_path, monkeypatch, caplog
):
    from adapters.mediacrawler import runner
    import json

    data_dir = tmp_path / "data" / "douyin" / "jsonl"
    data_dir.mkdir(parents=True)
    output = data_dir / "search_comments_2026-07-06.jsonl"
    output.write_text(
        json.dumps(
            {
                "content": "想了解报名条件",
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

    async def fake_run_with_retry(*args, **kwargs):
        raise MediaCrawlerProcessError(
            "MediaCrawler douyin failed: 登录按钮未找到",
            workspace=tmp_path,
            stdout_text="",
            stderr_text="登录按钮未找到",
        )

    monkeypatch.setattr(
        runner, "_run_mediacrawler_process_with_retry", fake_run_with_retry
    )
    caplog.set_level("WARNING", logger="thunder.mediacrawler")

    result = await runner.run_platform("douyin", ["征兵"], workspace=tmp_path)

    assert result == [
        {
            "text": "想了解报名条件",
            "source_name": "lead-user",
            "source_sec_uid": "sec-1",
            "source_short_id": "comment-1",
            "source_video_id": "video-1",
            "source_keyword": "征兵",
            "source_platform": "douyin",
        }
    ]
    assert output.exists()
    assert "salvaging partial output" in caplog.text


@pytest.mark.asyncio
async def test_run_platform_does_not_move_caller_workspace_on_retry_timeout(
    tmp_path, monkeypatch
):
    from adapters.mediacrawler import runner

    workspace = tmp_path / "caller_workspace"
    (workspace / "config").mkdir(parents=True)
    (workspace / "config" / "base_config.py").write_text("", encoding="utf-8")
    calls = []

    async def fake_run_process(cmd, *, mc_dir, platform, timeout_seconds=None):
        calls.append(mc_dir)
        raise MediaCrawlerTimeoutError(
            "MediaCrawler douyin timed out",
            workspace=mc_dir,
        )

    monkeypatch.setattr(runner, "_run_mediacrawler_process", fake_run_process)

    with pytest.raises(MediaCrawlerTimeoutError):
        await runner.run_platform("douyin", ["征兵"], workspace=workspace)

    assert workspace.exists()
    assert (workspace / "config" / "base_config.py").exists()
    assert calls[0] == workspace


@pytest.mark.asyncio
async def test_mediacrawler_process_decodes_gb18030_stderr(tmp_path, monkeypatch):
    from adapters.mediacrawler import runner

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return b"", "登录按钮未找到".encode("gb18030")

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    with pytest.raises(MediaCrawlerProcessError) as exc_info:
        await runner._run_mediacrawler_process(
            ["python", "main.py"],
            mc_dir=tmp_path,
            platform="douyin",
            timeout_seconds=1,
        )

    assert "登录按钮未找到" in str(exc_info.value)
    assert exc_info.value.stderr_text == "登录按钮未找到"
