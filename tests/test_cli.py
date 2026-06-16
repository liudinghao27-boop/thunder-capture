"""Tests for cli.py bug fixes."""

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import project-root cli.py explicitly to avoid collision with deps/crawl4ai/cli.py.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CLI_PATH = _PROJECT_ROOT / "cli.py"
spec = importlib.util.spec_from_file_location("cli", _CLI_PATH)
cli = importlib.util.module_from_spec(spec)
sys.modules["cli"] = cli
spec.loader.exec_module(cli)


def test_add_blogger_short_id_position():
    """CLI add_blogger call must include short_id positional argument."""
    with patch("cli.add_blogger") as mock_add:
        mock_add.return_value = True
        args = argparse.Namespace(
            add=["sec-1", "nick-1"],
            industry="test-ind",
            list=False,
            pause=None,
        )
        cli.cmd_bloggers(args)

    mock_add.assert_called_once_with(
        "sec-1",
        "",
        "nick-1",
        industry_slug="test-ind",
    )


def test_pause_uses_mark_target_inactive():
    """CLI pause must call mark_target_inactive from task_stats."""
    with patch("cli.mark_target_inactive") as mock_inactive:
        mock_inactive.return_value = None
        args = argparse.Namespace(
            add=None,
            industry="test-ind",
            list=False,
            pause="sec-1",
        )
        cli.cmd_bloggers(args)

    mock_inactive.assert_called_once_with("sec-1", "test-ind")


def test_cmd_send_does_not_call_reclaim_stale_claims():
    """cmd_send should run without referencing undefined reclaim_stale_claims."""
    with patch("cli.run_senders") as mock_run, \
         patch("cli.queue_stats", return_value={"pending": 0, "done": 0}), \
         patch("cli.load_industry") as mock_load:
        mock_ind = MagicMock()
        mock_ind.slug = "test-ind"
        mock_load.return_value = mock_ind
        args = argparse.Namespace(industry="test-ind", devices="")
        cli.cmd_send(args)

    mock_run.assert_called_once()
