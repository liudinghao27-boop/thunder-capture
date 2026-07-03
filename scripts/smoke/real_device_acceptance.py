"""Guarded real-device acceptance for one dedicated QA recipient."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.adb_keyboard import adb_device_health, prepare_adb_keyboard  # noqa: E402
from core.agent.executor import PhoneAgentExecutor  # noqa: E402
from core.agent.memory import AgentMemoryStore  # noqa: E402
from core.agent.perception import PerceptionService  # noqa: E402
from core.agent.planner import Planner  # noqa: E402
from core.agent.decision import decide_next_action  # noqa: E402
from core.agent.state import Observation  # noqa: E402
from core.config import load_industry, load_system  # noqa: E402
from core.task.runner import TaskGraphRunner  # noqa: E402


def _normalize_identifier(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def observed_profile_matches(target: str, elements: list[dict[str, Any]], ocr_text: str) -> bool:
    """Require the target to equal one visible label, never a substring."""
    expected = _normalize_identifier(target)
    if not expected:
        return False
    labels: list[str] = []
    for element in elements:
        labels.extend(
            str(element.get(key) or "")
            for key in ("text", "content_desc", "content-desc")
            if element.get(key)
        )
    labels.extend(line.strip() for line in str(ocr_text or "").splitlines() if line.strip())
    return any(_normalize_identifier(label) == expected for label in labels)


def validate_live_send(args: argparse.Namespace, *, profile_matches: bool) -> None:
    if not args.live_send:
        return
    if args.confirm_target != args.target:
        raise ValueError("--confirm-target must exactly equal --target")
    if args.max_sends != 1:
        raise ValueError("--max-sends must be exactly 1 for acceptance")
    if not profile_matches:
        raise ValueError("observed profile identifier does not exactly match --target")


def _observation_from_dict(data: dict[str, Any]) -> Observation:
    return Observation(
        device_id=str(data.get("device_id") or ""),
        adb_serial=str(data.get("adb_serial") or ""),
        screen=str(data.get("screen") or "unknown"),
        confidence=float(data.get("confidence") or 0.0),
        blocker=str(data.get("blocker") or ""),
        evidence=list(data.get("evidence") or []),
        elements=list(data.get("elements") or []),
        screenshot_path=str(data.get("screenshot_path") or ""),
        ocr_text=str(data.get("ocr_text") or ""),
        ocr_status=str(data.get("ocr_status") or ""),
        ocr_provider=str(data.get("ocr_provider") or ""),
        package_name=str(data.get("package_name") or ""),
        activity=str(data.get("activity") or ""),
        errors=list(data.get("errors") or []),
        captured_at=str(data.get("captured_at") or ""),
    )


def summarize_acceptance_evidence(
    *,
    observation: dict[str, Any],
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    action_result = result.get("action_result") if isinstance(result.get("action_result"), dict) else {}
    payload = action_result.get("payload") if isinstance(action_result.get("payload"), dict) else {}
    agent_decisions = payload.get("agent_decisions") if isinstance(payload.get("agent_decisions"), dict) else {}
    send_verification = payload.get("send_verification") if isinstance(payload.get("send_verification"), dict) else {}

    before_decision = agent_decisions.get("before") if isinstance(agent_decisions.get("before"), dict) else {}
    after_decision = agent_decisions.get("after") if isinstance(agent_decisions.get("after"), dict) else {}
    if not before_decision:
        before_decision = decide_next_action(_observation_from_dict(observation), goal="send_dm").as_dict()

    screenshot_path = (
        str(send_verification.get("screenshot_path") or "")
        or str(after_decision.get("screenshot") or "")
        or str(before_decision.get("screenshot") or "")
        or str(observation.get("screenshot_path") or "")
    )
    return {
        "before_decision": before_decision,
        "after_decision": after_decision,
        "send_verification": send_verification,
        "screenshot_path": screenshot_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="ADB device serial")
    parser.add_argument("--industry", required=True, help="Industry slug")
    parser.add_argument("--target", required=True, help="Dedicated QA recipient identifier")
    parser.add_argument("--message", required=True, help="Single acceptance message")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Capture evidence without phone actions")
    mode.add_argument("--live-send", action="store_true", help="Allow exactly one guarded send")
    parser.add_argument("--confirm-target", default="")
    parser.add_argument("--max-sends", type=int, default=0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "data" / "acceptance",
        help="Evidence root directory",
    )
    return parser


def _write_event(log_path: Path, event: str, context: dict[str, Any], **payload: Any) -> None:
    row = {"event": event, **context, **payload}
    line = json.dumps(row, ensure_ascii=False, default=str)
    print(line, flush=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _new_context(serial: str) -> dict[str, str]:
    correlation_id = str(uuid.uuid4())
    job_id = f"accept-job-{correlation_id}"
    return {
        "correlation_id": correlation_id,
        "job_id": job_id,
        "device_id": serial,
        "task_id": f"accept-task-{correlation_id}",
        "claim_token": f"{job_id}:accept:{uuid.uuid4()}",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    context = _new_context(args.serial)
    run_dir = args.output_dir.resolve() / context["correlation_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    log_path = run_dir / "run.jsonl"
    _write_event(log_path, "acceptance_started", context, mode="live" if args.live_send else "dry_run")

    health = adb_device_health(args.serial)
    keyboard = prepare_adb_keyboard(args.serial, install_if_missing=True) if health["online"] else {
        "serial": args.serial,
        "installed": False,
        "active": False,
        "ok": False,
        "message": health.get("error") or "device offline",
    }
    _write_event(log_path, "device_checked", context, health=health, keyboard=keyboard)
    if not health["online"]:
        raise RuntimeError(f"ADB device is offline: {health.get('error') or args.serial}")

    perception = PerceptionService()
    observation = perception.observe(
        device_id=args.serial,
        adb_serial=args.serial,
        screenshot_dir=run_dir / "screenshots",
    )
    profile_matches = observed_profile_matches(args.target, observation.elements, observation.ocr_text)
    plan = Planner().plan_dm("douyin", args.target, args.target, args.message).as_dict()
    report: dict[str, Any] = {
        **context,
        "mode": "live" if args.live_send else "dry_run",
        "industry": args.industry,
        "target": args.target,
        "message": args.message,
        "health": health,
        "keyboard": keyboard,
        "profile_matches": profile_matches,
        "observation": observation.as_dict(),
        "planned_action": plan,
        "status": "evidence_captured",
    }
    evidence_summary = summarize_acceptance_evidence(observation=observation.as_dict())
    report.update(evidence_summary)
    _write_event(
        log_path,
        "evidence_captured",
        context,
        screen=observation.screen,
        confidence=observation.confidence,
        blocker=observation.blocker,
        screenshot_path=observation.screenshot_path,
        ocr_status=observation.ocr_status,
        profile_matches=profile_matches,
        before_decision=evidence_summary["before_decision"],
        after_decision=evidence_summary["after_decision"],
        send_verification=evidence_summary["send_verification"],
    )

    if args.dry_run:
        report["status"] = "dry_run_ready" if keyboard["ok"] and not observation.blocker else "dry_run_blocked"
    else:
        validate_live_send(args, profile_matches=profile_matches)
        industry = load_industry(args.industry)
        system = load_system()
        glm = system.get("autoglm", {})
        api_key = industry.zhipu_key or system.get("api_keys", {}).get("zhipu", "")
        if not api_key:
            raise RuntimeError("Zhipu/AutoGLM API key is not configured")
        memory = AgentMemoryStore(user_id=industry.user_id, industry_slug=industry.slug)
        memory.remember(
            "acceptance_started",
            {**context, "target": args.target, "max_sends": args.max_sends},
            device_id=args.serial,
            subject_id=context["job_id"],
            subject_type="job",
        )
        executor = PhoneAgentExecutor(
            adb_serial=args.serial,
            base_url=str(glm.get("base_url") or ""),
            model_name=str(glm.get("model") or "autoglm-phone"),
            api_key=str(api_key),
        )
        runner = TaskGraphRunner(memory=memory, perception=perception, screenshot_dir=run_dir / "screenshots")
        try:
            result = runner.run_douyin_dm(
                device_id=args.serial,
                adb_serial=args.serial,
                search_target=args.target,
                user_name=args.target,
                message=args.message,
                execute_goal=executor.execute_goal,
                job_id=context["job_id"],
                task_id=context["task_id"],
            )
        finally:
            executor.stop()
        report["result"] = result.as_dict()
        report["status"] = result.status
        evidence_summary = summarize_acceptance_evidence(
            observation=observation.as_dict(),
            result=result.as_dict(),
        )
        report.update(evidence_summary)
        _write_event(
            log_path,
            "live_send_finished",
            context,
            ok=result.ok,
            status=result.status,
            before_decision=evidence_summary["before_decision"],
            after_decision=evidence_summary["after_decision"],
            send_verification=evidence_summary["send_verification"],
            screenshot_path=evidence_summary["screenshot_path"],
        )

    report_path = run_dir / "report.json"
    report["user_id"] = str(getattr(args, "user_id", "") or "")
    report["device_id"] = str(getattr(args, "device_id", "") or context["device_id"])
    evidence_files = [
        path for path in [
            report.get("screenshot_path"),
            (report.get("observation") or {}).get("screenshot_path"),
        ]
        if path
    ]
    report["evidence_files"] = list(dict.fromkeys(str(path) for path in evidence_files))
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _write_event(log_path, "acceptance_finished", context, status=report["status"], report_path=str(report_path))
    return report


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": report["status"] in {"dry_run_ready", "done"}, **report}, ensure_ascii=False, default=str))
    return 0 if report["status"] in {"dry_run_ready", "done"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
