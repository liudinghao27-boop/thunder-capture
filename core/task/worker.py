import json
import time
import random
import logging
import threading

from core.agent.executor import PhoneAgentExecutor
from core.agent.memory import AgentMemoryStore
from core.agent.planner import Planner
from core.task.scheduler import MatrixTaskScheduler
from core.device.manager import load_active_devices
from core.device.supervisor import DeviceSupervisor
from core.strategy.policy import is_send_window_open
from core.strategy.risk import RiskManager
from core.config import IndustryConfig, load_system
from core.constants import (
    DEFAULT_DAILY_LIMIT,
    DEFAULT_MIN_INTERVAL_SEC,
    DEFAULT_AGENT_MAX_STEPS,
)
from server.services.abtest import select_reply_variant

log = logging.getLogger("thunder.worker")
_SENDER_JOIN_POLL_SECONDS = 2
_SENDER_CANCEL_GRACE_SECONDS = 20

_reply_client = None
_loaded_reply_key = None


def _get_reply_client(api_key: str = ""):
    global _reply_client, _loaded_reply_key
    sys_cfg = load_system()
    key = api_key or sys_cfg["api_keys"]["deepseek"]
    if _reply_client is None or key != _loaded_reply_key:
        import httpx
        from openai import OpenAI

        _reply_client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        _loaded_reply_key = key
    return _reply_client


def _get_glm_config(api_key: str = ""):
    sys_cfg = load_system()
    glm = sys_cfg["autoglm"]
    return (
        glm["base_url"],
        glm["model"],
        glm.get("vision_model", "glm-4v"),
        api_key or sys_cfg["api_keys"]["zhipu"],
    )


REPLY_HEADER = "你是{role}。{style}\n"
REPLY_FOOTER = "\n直接给回复文案(15-30字)，不要加微信/链接/emoji，不要解释。"
TONE_VARIATIONS = [
    "语气要热情主动",
    "语气要稳重可靠",
    "语气要简洁专业",
    "语气要亲切自然",
    "语气要像个老大哥",
]


class DeviceWorker:
    def __init__(
        self,
        device_id: str,
        adb_serial: str,
        industry: IndustryConfig,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
        min_interval: int = DEFAULT_MIN_INTERVAL_SEC,
        should_stop=None,
        job_id: str = "",
    ):
        self.device_id = device_id
        self.adb_serial = adb_serial
        self.industry = industry
        self.daily_limit = daily_limit
        self.min_interval = min_interval
        self.should_stop = should_stop
        self.job_id = job_id

        self.industry_slug = getattr(self.industry, "slug", "") or ""
        self.owner_user_id = getattr(self.industry, "user_id", "") or ""

        self._executor = None
        self._planner = Planner()
        self._memory = AgentMemoryStore(
            user_id=self.owner_user_id, industry_slug=self.industry_slug
        )
        self._supervisor = DeviceSupervisor(
            user_id=self.owner_user_id, industry_slug=self.industry_slug
        )
        self._risk = RiskManager()

        self._scheduler = MatrixTaskScheduler(
            industry_slug=self.industry_slug,
            owner_user_id=self.owner_user_id,
            global_daily_limit=int(
                getattr(self.industry, "global_daily_limit", 0) or 0
            ),
            daily_send_max=int(getattr(self.industry, "daily_send_max", 0) or 0),
            device_daily_limit=int(self.daily_limit or 0),
            hourly_send_limit=int(getattr(self.industry, "hourly_send_limit", 0) or 0),
            job_id=self.job_id,
        )

    def _generate_reply(self, task: dict) -> tuple[str, str]:
        variant = select_reply_variant(getattr(self.industry, "reply_variants", None))
        if variant:
            tone = variant.get("reply_tone") or getattr(self.industry, "reply_tone", "")
            style = variant.get("reply_style") or getattr(
                self.industry, "reply_style", ""
            )
            hook = variant.get("reply_hook") or getattr(self.industry, "reply_hook", "")
            variant_id = variant.get("id", "")
        else:
            tone = getattr(self.industry, "reply_tone", "")
            style = getattr(self.industry, "reply_style", "")
            hook = getattr(self.industry, "reply_hook", "")
            variant_id = ""

        comment_text = task.get("text", "")
        question = ""
        reply_topic = ""
        try:
            raw = task.get("matched_categories", "[]")
            if raw and raw != "[]":
                meta = json.loads(raw)
                if isinstance(meta, dict):
                    question = meta.get("question", "")
                    reply_topic = meta.get("reply_topic", "")
        except Exception:
            pass

        hints = ""
        if question:
            hints += f"用户问题：{question}。"
        if reply_topic:
            hints += f"回复方向：{reply_topic}。"

        tone_variation = random.choice(TONE_VARIATIONS)
        hook_prompt = ""
        if hook:
            hook_prompt = f"\n\n⚠️【核心要求】私信的结尾必须非常自然地带上这个钩子话术引导回复：{hook}"

        try:
            prompt = (
                REPLY_HEADER.format(role=tone, style=f"{style}。{tone_variation}")
                + (f"{hints}\n" if hints else "")
                + f"对方评论: {comment_text}"
                + hook_prompt
                + REPLY_FOOTER
            )
            resp = _get_reply_client(
                getattr(self.industry, "deepseek_key", "")
            ).chat.completions.create(
                model="deepseek-v4-flash",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                temperature=0.9,
            )
            content = resp.choices[0].message.content
            if not content:
                raise ValueError("LLM returned empty content")
            return content.strip()[:60], variant_id
        except Exception:
            fallbacks = [
                f"你好，我是{tone}，看到你的评论，需要帮忙吗？",
                "关于你问的，我比较了解，方便的话私聊。",
            ]
            return random.choice(fallbacks), variant_id

    def _init_agent_safe(self) -> bool:
        if self._executor:
            return True
        try:
            from core.adb_keyboard import prepare_adb_keyboard

            status = prepare_adb_keyboard(self.adb_serial, install_if_missing=True)
            if not status.get("ok"):
                log.error(f"[{self.device_id}] ADB Keyboard not ready")
                return False

            glm_base, glm_model, _, glm_key = _get_glm_config(
                getattr(self.industry, "zhipu_key", "")
            )
            self._executor = PhoneAgentExecutor(
                adb_serial=self.adb_serial,
                base_url=glm_base,
                model_name=glm_model,
                api_key=glm_key,
                should_stop=self.should_stop,
                max_steps=DEFAULT_AGENT_MAX_STEPS,
            ).start()
            return True
        except Exception as e:
            log.error(f"[{self.device_id}] PhoneAgent init failed: {e}")
            return False

    def run(self):
        summary = {
            "device_id": self.device_id,
            "adb_serial": self.adb_serial,
            "industry_slug": self.industry_slug,
            "status": "running",
            "sent": 0,
            "failed": 0,
            "cancelled": False,
            "error": "",
            "daily_limit_reached": False,
            "global_limit_reached": False,
            "no_task": False,
        }
        gate = self._supervisor.preflight(
            device_id=self.device_id, adb_serial=self.adb_serial, job_id=self.job_id
        )
        if not gate.ok:
            summary.update(status=gate.status, error=gate.reason)
            return summary

        try:
            while True:
                if self.should_stop and self.should_stop():
                    summary.update(status="cancelled", cancelled=True)
                    break

                claim = self._scheduler.claim_for_device(self.device_id)

                if not claim.ok:
                    if claim.reason == "device_daily_limit_reached":
                        summary.update(status="daily_limit", daily_limit_reached=True)
                    elif claim.reason == "global_daily_limit_reached":
                        summary.update(
                            status="quota_reached", global_limit_reached=True
                        )
                    elif claim.reason == "device_rate_limited":
                        # Simulate wait
                        time.sleep(30)
                        continue
                    else:
                        summary.update(status="no_task", no_task=True)
                    break

                def _handle_send_failure(error_message: str) -> None:
                    self._scheduler.commit_task(
                        claim.task_id,
                        self.device_id,
                        "fail",
                        error_message[:500],
                        claim_token=claim_token,
                    )
                    summary["failed"] += 1
                    decision = self._risk.assess_action_result(
                        error_message,
                        consecutive_failures=int(summary.get("failed") or 0),
                    )
                    if decision.action == "isolate":
                        self._supervisor.mark_failure(
                            device_id=self.device_id,
                            job_id=self.job_id,
                            status="isolated",
                            error=decision.reason or error_message,
                        )
                        summary.update(
                            status="isolated", error=decision.reason or error_message
                        )
                    elif decision.action == "cooldown":
                        self._supervisor.mark_cooldown(
                            device_id=self.device_id,
                            job_id=self.job_id,
                            error=decision.reason or error_message,
                            hours=decision.cooldown_hours or 1,
                        )
                        summary.update(
                            status="cooldown", error=decision.reason or error_message
                        )

                task = claim.task
                claim_token = task.get("claim_token", "")
                reply_msg, variant_id = self._generate_reply(task)
                short_id = (
                    task.get("short_id")
                    or task.get("douyin_id")
                    or task.get("unique_id")
                    or task.get("user_id")
                    or task.get("sec_uid")
                    or ""
                )

                if not self._init_agent_safe():
                    error = "Agent init failed"
                    self._scheduler.commit_task(
                        claim.task_id,
                        self.device_id,
                        "fail",
                        error,
                        claim_token=claim_token,
                    )
                    self._supervisor.mark_failure(
                        device_id=self.device_id,
                        job_id=self.job_id,
                        status="keyboard_error",
                        error=error,
                    )
                    summary.update(status="keyboard_error", error=error)
                    summary["failed"] += 1
                    break

                try:
                    from core.agent.perception import PerceptionService
                    from core.task.runner import TaskGraphRunner

                    perception = PerceptionService()
                    runner = TaskGraphRunner(
                        memory=self._memory,
                        planner=self._planner,
                        perception=perception,
                    )
                    exec_result = runner.run_douyin_dm(
                        device_id=self.device_id,
                        adb_serial=self.adb_serial,
                        search_target=short_id,
                        user_name=task.get("source_name", ""),
                        message=reply_msg,
                        execute_goal=lambda goal: self._executor.execute_goal(goal),
                        job_id=self.job_id,
                        task_id=claim.task_id,
                    )

                    if exec_result.ok:
                        self._scheduler.commit_task(
                            claim.task_id,
                            self.device_id,
                            "done",
                            "",
                            claim_token=claim_token,
                            reply_variant_id=variant_id,
                        )
                        summary["sent"] += 1
                    else:
                        _handle_send_failure(
                            exec_result.message or exec_result.status or "send failed"
                        )
                        if summary["status"] in {"isolated", "cooldown"}:
                            break
                except Exception as e:
                    _handle_send_failure(str(e)[:500])
                    if summary["status"] in {"isolated", "cooldown"}:
                        break

                # Rest between sends
                wait = self.min_interval + random.randint(0, 30)
                for _ in range(wait):
                    if self.should_stop and self.should_stop():
                        break
                    time.sleep(1)

        finally:
            if self._executor:
                self._executor.stop()
            self._supervisor.mark_finished(
                device_id=self.device_id,
                job_id=self.job_id,
                status=summary["status"]
                if summary["status"] not in ("running", "cancelled")
                else "idle",
            )

        return summary


def _run_device(d: dict, industry: IndustryConfig, should_stop=None, job_id: str = ""):
    try:
        worker = DeviceWorker(
            device_id=d["id"],
            adb_serial=d.get("adb_serial", ""),
            industry=industry,
            daily_limit=d.get("daily_limit", industry.daily_limit),
            min_interval=d.get("min_interval_sec", DEFAULT_MIN_INTERVAL_SEC),
            should_stop=should_stop,
            job_id=job_id,
        )
        return worker.run()
    except Exception as e:
        log.error(f"[{d['id']}] fatal: {e}")
        return {"device_id": d["id"], "status": "failed", "error": str(e)[:500]}


def run_senders(
    industry: IndustryConfig,
    device_ids: list[str] | None = None,
    should_stop=None,
    job_id: str = "",
):
    """Dispatch send tasks to Celery workers (or fallback to threading).

    With Celery available:
      - Each device gets its own Celery task (auto-retry, rate-limited)
      - Workers can run on multiple machines
      - Tasks survive process restarts (Redis persistence)

    Fallback:
      - Native threading (original behavior, no Redis needed)
    """
    log.info(f"run_senders called with device_ids={device_ids}")
    if getattr(industry, "compliance_mode", False):
        log.info(
            "Compliance mode enabled for %s; skipping actual send.",
            getattr(industry, "slug", ""),
        )
        return {
            "ok": True,
            "skipped": True,
            "reason": "compliance_mode",
            "industry_slug": getattr(industry, "slug", ""),
            "message": "合规模式已开启，仅采集不发送。",
        }
    if not is_send_window_open(industry):
        log.info(
            "Send window closed for %s; skipping dispatch.",
            getattr(industry, "slug", ""),
        )
        return {
            "ok": True,
            "skipped": True,
            "reason": "outside_send_window",
            "industry_slug": getattr(industry, "slug", ""),
            "message": "当前不在允许的发送时段内。",
        }
    user_id = getattr(industry, "user_id", "") or ""
    requested_device_ids = [
        str(d).strip() for d in (device_ids or []) if str(d).strip()
    ]
    targets = [
        device.as_sender_dict()
        for device in load_active_devices(
            user_id=user_id, device_ids=requested_device_ids
        )
    ]

    if not targets:
        return {"ok": False, "error": "no available devices", "devices_total": 0}

    # ── Try Celery first ──
    try:
        from adapters.celery.send import send_dm_task
        from adapters.celery.app import app

        # Fail fast when the broker is unreachable so local/dev runs still send.
        try:
            with app.connection() as conn:
                conn.connect()
        except Exception as exc:
            log.warning(
                "Celery broker unreachable (%s), falling back to threading", exc
            )
            raise
        log.info("Using Celery backend for %d devices", len(targets))

        task_results = []
        for d in targets:
            # Submit one task per device — Celery handles concurrency + rate limiting
            async_result = send_dm_task.delay(
                device_id=d["id"],
                adb_serial=d.get("adb_serial", ""),
                industry_slug=getattr(industry, "slug", ""),
                user_id=user_id,
                task_data={
                    "industry_name": getattr(industry, "name", ""),
                    "reply_tone": getattr(industry, "reply_tone", ""),
                    "reply_style": getattr(industry, "reply_style", ""),
                    "reply_variants": getattr(industry, "reply_variants", []),
                    "daily_limit": d.get("daily_limit", 15),
                    "min_interval_sec": d.get("min_interval_sec", 90),
                    "daily_send_max": int(getattr(industry, "daily_send_max", 0) or 0),
                    "global_daily_limit": int(
                        getattr(industry, "global_daily_limit", 0) or 0
                    ),
                    "hourly_send_limit": int(
                        getattr(industry, "hourly_send_limit", 0) or 0
                    ),
                    "job_id": job_id,
                },
                reply_msg="",  # Celery task generates reply itself
            )
            task_results.append(
                {
                    "device_id": d["id"],
                    "task_id": async_result.id,
                    "status": "dispatched",
                }
            )

        return {
            "ok": True,
            "backend": "celery",
            "industry_slug": getattr(industry, "slug", ""),
            "devices_total": len(targets),
            "sent_total": 0,  # Async — check Flower for progress
            "failed_total": 0,
            "devices": task_results,
            "monitor_url": "http://localhost:5555",
        }
    except ImportError:
        log.info("Celery not available, falling back to threading")
    except Exception as exc:
        log.warning("Celery dispatch failed (%s), falling back to threading", exc)

    # ── Fallback: native threading ──
    threads = []
    thread_devices = []
    results = []
    results_lock = threading.Lock()

    for d in targets:

        def _target(device=d):
            result = _run_device(device, industry, should_stop, job_id=job_id)
            with results_lock:
                results.append(result or {})

        t = threading.Thread(target=_target, name=f"sender-{d['id']}", daemon=True)
        t.start()
        threads.append(t)
        thread_devices.append((t, d))

    cancel_started_at = None
    while True:
        alive = [t for t in threads if t.is_alive()]
        if not alive:
            break
        if should_stop and should_stop():
            if cancel_started_at is None:
                cancel_started_at = time.monotonic()
            if time.monotonic() - cancel_started_at >= _SENDER_CANCEL_GRACE_SECONDS:
                with results_lock:
                    completed_results = list(results)
                completed_device_ids = {
                    str(result.get("device_id"))
                    for result in completed_results
                    if result.get("device_id")
                }
                pending_results = [
                    {
                        "device_id": d["id"],
                        "status": "cancelling_timeout",
                        "sent": 0,
                        "failed": 0,
                        "cancelled": True,
                        "error": "Cancellation requested while device worker was still stopping.",
                    }
                    for t, d in thread_devices
                    if t.is_alive() and str(d.get("id")) not in completed_device_ids
                ]
                all_results = completed_results + pending_results
                return {
                    "ok": False,
                    "backend": "threading",
                    "cancelled": True,
                    "error": "Cancellation requested; some device workers did not stop within grace period.",
                    "industry_slug": getattr(industry, "slug", ""),
                    "devices_total": len(targets),
                    "sent_total": sum(int(r.get("sent") or 0) for r in all_results),
                    "failed_total": sum(int(r.get("failed") or 0) for r in all_results),
                    "devices": all_results,
                }
        for t in alive:
            t.join(timeout=_SENDER_JOIN_POLL_SECONDS)

    sent_total = sum(int(r.get("sent") or 0) for r in results)
    failed_total = sum(int(r.get("failed") or 0) for r in results)

    return {
        "ok": True,
        "backend": "threading",
        "industry_slug": getattr(industry, "slug", ""),
        "devices_total": len(targets),
        "sent_total": sent_total,
        "failed_total": failed_total,
        "devices": results,
    }
