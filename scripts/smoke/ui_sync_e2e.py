"""End-to-end UI/API synchronization checks for the Web UI.

The script can run against an existing server or start a temporary local
SQLite-backed server. It logs in through the browser, captures backend API
responses, reads rendered DOM state, and compares both sides through explicit
field mappings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class SyncMapping:
    name: str
    selector: str
    api_path: str
    kind: str = "text"


def get_payload_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if part == "length":
            return len(current or [])
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _normalize(value: Any, kind: str) -> Any:
    if kind == "int":
        if value is None or value == "":
            return 0
        text = str(value).strip()
        digits = "".join(ch for ch in text if ch.isdigit() or ch == "-")
        return int(digits or 0)
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "ok"}
    return "" if value is None else str(value).strip()


def compare_ui_snapshot(
    api_payload: dict[str, Any],
    ui_snapshot: dict[str, Any],
    mappings: list[SyncMapping],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for mapping in mappings:
        expected = _normalize(get_payload_path(api_payload, mapping.api_path), mapping.kind)
        actual = _normalize(ui_snapshot.get(mapping.selector), mapping.kind)
        if expected != actual:
            mismatches.append(
                {
                    "name": mapping.name,
                    "selector": mapping.selector,
                    "api_path": mapping.api_path,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return mismatches


def summarize_run(
    *,
    results: list[dict[str, Any]],
    started_at: str,
    duration_seconds: float,
) -> dict[str, Any]:
    failed = sum(1 for result in results if not result.get("ok"))
    total = len(results)
    return {
        "ok": failed == 0,
        "started_at": started_at,
        "duration_seconds": round(duration_seconds, 3),
        "total": total,
        "passed": total - failed,
        "failed": failed,
        "results": results,
    }


def _server_alive(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/", timeout=3) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def _start_server(base_url: str) -> subprocess.Popen | None:
    if _server_alive(base_url):
        return None
    env = os.environ.copy()
    env.setdefault("THUNDER_DATABASE_URL", "sqlite:///data/thunder.db")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    python_exe = Path(".venv/Scripts/python.exe")
    executable = str(python_exe) if python_exe.exists() else sys.executable
    logs = Path("tmp")
    logs.mkdir(exist_ok=True)
    stdout = (logs / "ui-sync-server.out.log").open("w", encoding="utf-8")
    stderr = (logs / "ui-sync-server.err.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        stdout=stdout,
        stderr=stderr,
        env=env,
    )
    for _ in range(30):
        if process.poll() is not None:
            raise RuntimeError("Temporary server exited early; see tmp/ui-sync-server.err.log")
        if _server_alive(base_url):
            return process
        time.sleep(1)
    process.terminate()
    raise TimeoutError(f"Server did not become healthy at {base_url}")


async def _browser_check(base_url: str, artifacts_dir: Path, headful: bool) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    api_responses: dict[str, Any] = {}
    results: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = None
        launch_errors: list[str] = []
        for launch in (
            lambda: playwright.chromium.launch(headless=not headful),
            lambda: playwright.chromium.launch(channel="chrome", headless=not headful),
            lambda: playwright.chromium.launch(channel="msedge", headless=not headful),
        ):
            try:
                browser = await launch()
                break
            except Exception as exc:  # pragma: no cover - depends on local browsers
                launch_errors.append(str(exc).splitlines()[0])
        if browser is None:
            raise RuntimeError("No Playwright browser available: " + " | ".join(launch_errors))

        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: console_errors.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error"
            else None,
        )

        async def capture_response(response):
            url = response.url
            if "/api/" not in url:
                return
            try:
                body = await response.json()
            except Exception:
                body = await response.text()
            api_responses[url] = {
                "status": response.status,
                "body": body,
            }

        page.on("response", capture_response)

        username = f"ui_sync_{int(time.time())}"
        password = "CodexTest123!"

        await page.goto(base_url.rstrip("/") + "/", wait_until="domcontentloaded")
        await page.wait_for_selector("#auth-username", timeout=15000)
        results.append(
            {
                "name": "permission: unauthenticated users see login form",
                "ok": True,
                "mismatches": [],
            }
        )

        await page.click("#tab-register")
        await page.fill("#auth-username", username)
        await page.fill("#auth-password", password)
        await page.click("#auth-submit-btn")
        await page.wait_for_function("() => !!localStorage.getItem('thunder_token')", timeout=20000)
        await page.wait_for_selector('[data-nav="overview"]', timeout=20000)

        token = await page.evaluate("() => localStorage.getItem('thunder_token')")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        industry_payload = {
            "name": "UI同步灰度项目",
            "slug": f"ui-sync-{int(time.time())}",
            "keywords": ["同步测试", "自动化校验", "前后端一致"],
            "platforms": ["douyin"],
            "reply_tone": "测试顾问",
            "reply_style": "简洁明确",
            "categories": ["同步测试"],
        }
        create_industry = await page.evaluate(
            """async ({payload, headers}) => {
                const r = await fetch('/api/industries', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify(payload)
                });
                return {status: r.status, body: await r.json()};
            }""",
            {"payload": industry_payload, "headers": headers},
        )
        results.append(
            {
                "name": "data submit: create industry API accepts UI-visible data",
                "ok": create_industry["status"] == 201,
                "mismatches": [] if create_industry["status"] == 201 else [create_industry],
            }
        )
        created_industry_id = (create_industry.get("body") or {}).get("id")

        await page.click('[data-nav="overview"]')
        await page.wait_for_timeout(1000)
        dashboard_state = await page.evaluate(
            """async headers => {
                const r = await fetch('/api/dashboard/state', {headers});
                return {status: r.status, body: await r.json()};
            }""",
            headers,
        )
        ui_dashboard = {
            "#stat-industries": await page.locator("#stat-industries").inner_text(),
            "#stat-devices": await page.locator("#stat-devices").inner_text(),
        }
        dashboard_mismatches = compare_ui_snapshot(
            dashboard_state["body"],
            ui_dashboard,
            [
                SyncMapping(
                    "dashboard project count",
                    "#stat-industries",
                    "project.industry_count",
                    "int",
                ),
                SyncMapping(
                    "dashboard device count",
                    "#stat-devices",
                    "device_matrix.total",
                    "int",
                ),
            ],
        )
        results.append(
            {
                "name": "dashboard: rendered counters match /api/dashboard/state",
                "ok": dashboard_state["status"] == 200 and not dashboard_mismatches,
                "mismatches": dashboard_mismatches,
            }
        )

        await page.click('[data-nav="industries"]')
        await page.wait_for_timeout(1200)
        industries = await page.evaluate(
            """async headers => {
                const r = await fetch('/api/industries', {headers});
                return {status: r.status, body: await r.json()};
            }""",
            headers,
        )
        grid_text = await page.locator("#industries-grid").inner_text()
        industry_mismatches = []
        if industries["status"] != 200:
            industry_mismatches.append(
                {
                    "name": "industries api status",
                    "expected": 200,
                    "actual": industries["status"],
                }
            )
        for industry in industries["body"]:
            if industry["name"] not in grid_text or industry["slug"] not in grid_text:
                industry_mismatches.append(
                    {
                        "name": "industry card text",
                        "expected": {"name": industry["name"], "slug": industry["slug"]},
                        "actual": grid_text[:500],
                    }
                )
        results.append(
            {
                "name": "industries: card grid matches /api/industries",
                "ok": not industry_mismatches,
                "mismatches": industry_mismatches,
            }
        )

        await page.click('[data-nav="tasks"]')
        await page.wait_for_timeout(1200)
        selected_industry = await page.locator("#task-filter-industry").input_value()
        leads = await page.evaluate(
            """async ({headers, slug}) => {
                const r = await fetch(`/api/leads?industry_slug=${encodeURIComponent(slug)}&limit=50`, {headers});
                return {status: r.status, body: await r.json()};
            }""",
            {"headers": headers, "slug": selected_industry},
        )
        task_rows = await page.locator("#tasks-table-body tr").count()
        expected_rows = max(1, len((leads["body"] or {}).get("leads", [])))
        results.append(
            {
                "name": "pagination/rendering: task table row count follows /api/leads limit=50",
                "ok": leads["status"] == 200 and task_rows == expected_rows,
                "mismatches": []
                if leads["status"] == 200 and task_rows == expected_rows
                else [{"name": "task rows", "expected": expected_rows, "actual": task_rows}],
            }
        )

        await page.click('[data-nav="jobs"]')
        await page.wait_for_timeout(1000)
        jobs = await page.evaluate(
            """async headers => {
                const r = await fetch('/api/jobs?limit=100', {headers});
                return {status: r.status, body: await r.json()};
            }""",
            headers,
        )
        job_rows = await page.locator("#jobs-table-body tr").count()
        expected_job_rows = max(1, len(jobs["body"]))
        results.append(
            {
                "name": "jobs: rendered rows match /api/jobs empty/data state",
                "ok": jobs["status"] == 200 and job_rows == expected_job_rows,
                "mismatches": []
                if jobs["status"] == 200 and job_rows == expected_job_rows
                else [{"name": "job rows", "expected": expected_job_rows, "actual": job_rows}],
            }
        )

        send_error_response = await page.context.request.post(
            base_url.rstrip("/") + "/api/jobs/send/start",
            headers=headers,
            data={"industry_slug": "missing-industry"},
        )
        send_error = {
            "status": send_error_response.status,
            "body": await send_error_response.json(),
        }
        results.append(
            {
                "name": "error contract: invalid send request exposes backend error code/detail",
                "ok": send_error["status"] == 404 and bool(send_error["body"].get("detail")),
                "mismatches": []
                if send_error["status"] == 404 and bool(send_error["body"].get("detail"))
                else [{"name": "send error", "expected": "404 with detail", "actual": send_error}],
            }
        )

        await page.click('[data-nav="settings"]')
        await page.wait_for_timeout(1000)
        settings = await page.evaluate(
            """async headers => {
                const r = await fetch('/api/auth/settings', {headers});
                return {status: r.status, body: await r.json()};
            }""",
            headers,
        )
        settings_visible = await page.locator("#settings-deepseek-key").is_visible()
        results.append(
            {
                "name": "permission: authenticated settings UI matches /api/auth/settings",
                "ok": settings["status"] == 200 and settings_visible,
                "mismatches": []
                if settings["status"] == 200 and settings_visible
                else [{"name": "settings visibility", "expected": "200 and visible", "actual": settings}],
            }
        )

        screenshot = artifacts_dir / "final-state.png"
        await page.screenshot(path=str(screenshot), full_page=True)
        if console_errors:
            results.append(
                {
                    "name": "browser console has no runtime errors",
                    "ok": False,
                    "mismatches": [{"name": "console errors", "actual": console_errors[:20]}],
                }
            )

        if created_industry_id:
            await page.context.request.delete(
                base_url.rstrip("/") + f"/api/industries/{created_industry_id}",
                headers=headers,
            )
        await browser.close()

    (artifacts_dir / "api-responses.json").write_text(
        json.dumps(api_responses, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"results": results, "artifacts": {"screenshot": str(artifacts_dir / "final-state.png")}}


async def run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    artifacts_dir = Path(args.artifacts_dir) / datetime.now().strftime("%Y%m%d-%H%M%S")
    server_process = None
    if not args.no_start_server:
        server_process = _start_server(args.base_url)
    try:
        browser_result = await _browser_check(args.base_url, artifacts_dir, args.headful)
        summary = summarize_run(
            results=browser_result["results"],
            started_at=started_at,
            duration_seconds=time.perf_counter() - start,
        )
        summary["artifacts"] = browser_result["artifacts"]
        report_path = artifacts_dir / "report.json"
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["ok"] else 1
    except Exception as exc:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        summary = summarize_run(
            results=[{"name": "ui-sync runner", "ok": False, "mismatches": [{"error": str(exc)}]}],
            started_at=started_at,
            duration_seconds=time.perf_counter() - start,
        )
        (artifacts_dir / "report.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1
    finally:
        if server_process is not None:
            server_process.terminate()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Web UI/API synchronization E2E checks.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--artifacts-dir", default="output/ui-sync")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--no-start-server", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
