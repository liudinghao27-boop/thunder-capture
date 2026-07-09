#!/usr/bin/env python3
"""抖音关键词采集稳定性测试脚本。

循环运行 N 次抖音关键词采集，记录每次的运行状态、评论数、风控与 CDP 失败
情况，并汇总输出到 docs/qa/stability_result.json。

启动前会自动检查 Chrome CDP 端口 61850 是否开放；未开放则退出并提示。

用法示例：
    python docs/qa/stability_test.py
    python docs/qa/stability_test.py --count 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import socket
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path so adapters can be imported even when the
# script is executed from a different working directory.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from adapters.mediacrawler.runner import (  # noqa: E402
    _run_mediacrawler_process,
    run_platform,
)

# Global container for subprocess output captured during a single run.
_captured_output = {"stdout": "", "stderr": ""}

# The original runner process runner, saved before monkey-patching.
_original_run_process = _run_mediacrawler_process


async def _capturing_run_process(
    cmd, *, mc_dir, platform, timeout_seconds=None
) -> tuple[str, str]:
    """Wrap the runner's process runner so we can inspect stdout/stderr.

    This lets us detect risk-control (empty aweme_list with successful login)
    and CDP connection failures without changing the runner's public contract.
    """
    try:
        stdout, stderr = await _original_run_process(
            cmd, mc_dir=mc_dir, platform=platform, timeout_seconds=timeout_seconds
        )
        _captured_output["stdout"] = stdout
        _captured_output["stderr"] = stderr
        return stdout, stderr
    except Exception as exc:
        # Preserve the exception message (runner often includes stderr tail).
        _captured_output["stdout"] = ""
        _captured_output["stderr"] = str(exc)
        raise


# Apply monkey patch to the runner module so run_platform uses the capturing wrapper.
import adapters.mediacrawler.runner  # noqa: E402

adapters.mediacrawler.runner._run_mediacrawler_process = _capturing_run_process


CDP_PORT = 61850
OUTPUT_FILE = BASE_DIR / "docs" / "qa" / "stability_result.json"


def is_cdp_port_open(port: int = CDP_PORT, timeout: float = 2.0) -> bool:
    """Check whether Chrome CDP is listening on the given port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _detect_pattern(text: str, patterns: list[str]) -> bool:
    return any(p in text for p in patterns)


def detect_cdp_failure(stdout: str, stderr: str) -> bool:
    """Return True if the captured output indicates a CDP connection failure."""
    return _detect_pattern(
        stdout + stderr,
        [
            "CDP browser launch failed",
            "CDP模式启动失败",
            "CDP connection failed",
            "Failed to connect to CDP",
            "Unable to connect to CDP",
            "Connecting to existing browser on port",
            "Make sure remote debugging is enabled",
            "Still waiting for browser",
            "Connection refused",
            "ConnectionRefusedError",
        ],
    )


def detect_login_success(stdout: str, stderr: str) -> bool:
    """Return True if the captured output indicates a successful login."""
    return _detect_pattern(
        stdout + stderr,
        [
            "说明登录成功",
            "Cookie login succeeded",
            "login succeeded",
            "treat as logged in",
        ],
    )


def detect_empty_aweme_list(stdout: str, stderr: str) -> bool:
    """Return True if the output contains an empty aweme_list log."""
    text = stdout + stderr
    # Match log lines like: "aweme_list:[]" or "aweme_list: []"
    if re.search(r"aweme_list\s*:\s*\[\s*\]", text):
        return True
    # Also check for explicit "no data" search responses.
    if "search douyin keyword" in text and "is empty" in text:
        return True
    return False


def _capture_output() -> tuple[str, str]:
    """Return the output captured by the monkey-patched runner."""
    return _captured_output.get("stdout", ""), _captured_output.get("stderr", "")


async def run_once(run_index: int) -> dict:
    """Execute a single collection run and return its recorded metrics."""
    started_at = datetime.now().isoformat()
    result = {
        "index": run_index,
        "timestamp": started_at,
        "success": False,
        "comment_count": 0,
        "risk_control": False,
        "cdp_failure": False,
        "error": "",
    }

    try:
        comments = await run_platform("douyin", ["高考志愿"], max_authors=2)
        stdout, stderr = _capture_output()

        result["comment_count"] = len(comments)
        result["success"] = len(comments) > 0
        result["cdp_failure"] = detect_cdp_failure(stdout, stderr)

        login_success = detect_login_success(stdout, stderr)
        empty_aweme = detect_empty_aweme_list(stdout, stderr)
        # Risk control: login succeeded but the search returned no aweme items and
        # therefore no comments.
        result["risk_control"] = (
            login_success and empty_aweme and len(comments) == 0 and not result["cdp_failure"]
        )

        if not result["success"] and not result["risk_control"] and not result["cdp_failure"]:
            result["error"] = "采集到 0 条评论（未识别到风控或 CDP 失败）"

    except Exception as exc:
        stdout, stderr = _capture_output()
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["cdp_failure"] = detect_cdp_failure(stdout, stderr) or detect_cdp_failure(
            str(exc), ""
        )

    return result


def print_summary(summary: dict) -> None:
    """Print the aggregated test results to the console."""
    print("\n稳定性测试完成:")
    print(f"  总次数: {summary['total']}")
    print(f"  成功次数: {summary['success_count']}")
    print(f"  成功率: {summary['success_rate']:.2%}")
    print(f"  风控触发率: {summary['risk_control_rate']:.2%}")
    print(f"  CDP 失败率: {summary['cdp_failure_rate']:.2%}")
    print(f"  平均评论数: {summary['average_comments']:.2f}")
    print(f"  结果已写入: {OUTPUT_FILE}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="抖音关键词采集稳定性测试")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=10,
        help="循环运行次数（默认 10）",
    )
    args = parser.parse_args()

    if not is_cdp_port_open(CDP_PORT):
        print(
            f"错误：Chrome CDP 端口 {CDP_PORT} 未开放。"
            "请先运行 docs/qa/launch_chrome_cdp.py 启动 Chrome 并开启远程调试。",
            file=sys.stderr,
        )
        sys.exit(1)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    results: list[dict] = []
    for i in range(1, args.count + 1):
        print(f"\n[{i}/{args.count}] 开始第 {i} 次采集...")
        result = await run_once(i)
        results.append(result)
        print(
            f"  成功={result['success']}, "
            f"评论数={result['comment_count']}, "
            f"风控={result['risk_control']}, "
            f"CDP失败={result['cdp_failure']}, "
            f"错误={result['error']!r}"
        )

    total = len(results)
    success_count = sum(1 for r in results if r["success"])
    risk_count = sum(1 for r in results if r["risk_control"])
    cdp_fail_count = sum(1 for r in results if r["cdp_failure"])
    total_comments = sum(r["comment_count"] for r in results)
    average_comments = total_comments / total if total else 0.0

    summary = {
        "total": total,
        "success_count": success_count,
        "success_rate": success_count / total if total else 0.0,
        "risk_control_rate": risk_count / total if total else 0.0,
        "cdp_failure_rate": cdp_fail_count / total if total else 0.0,
        "average_comments": average_comments,
        "runs": results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
