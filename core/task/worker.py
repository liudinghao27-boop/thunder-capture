import json
import time
import random
import logging
import threading
from typing import Optional

from openai import OpenAI

from core.agent.executor import PhoneAgentExecutor
from core.agent.memory import AgentMemoryStore
from core.agent.planner import Planner
from core.task.runner import TaskGraphRunner
from core.task.scheduler import MatrixTaskScheduler
from core.device.manager import load_active_devices
from core.device.supervisor import DeviceSupervisor
from core.strategy.risk import RiskManager
from core.strategy.wave import WaveStrategy
from core.strategy.policy import SendPolicyGate
from core.config import IndustryConfig, load_system

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
    return glm["base_url"], glm["model"], glm.get("vision_model", "glm-4v"), api_key or sys_cfg["api_keys"]["zhipu"]

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
    def __init__(self, device_id: str, adb_serial: str,
                 industry: IndustryConfig, daily_limit: int = 15,
                 min_interval: int = 90, should_stop=None,
                 job_id: str = ""):
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
        self._memory = AgentMemoryStore(user_id=self.owner_user_id, industry_slug=self.industry_slug)
        self._supervisor = DeviceSupervisor(user_id=self.owner_user_id, industry_slug=self.industry_slug)
        
        self._scheduler = MatrixTaskScheduler(
            industry_slug=self.industry_slug,
            owner_user_id=self.owner_user_id,
            global_daily_limit=int(getattr(self.industry, "global_daily_limit", 0) or 0),
            job_id=self.job_id,
        )

    def _generate_reply(self, task: dict) -> str:
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
        if question: hints += f"用户问题：{question}。"
        if reply_topic: hints += f"回复方向：{reply_topic}。"

        tone = random.choice(TONE_VARIATIONS)
        hook_prompt = ""
        if getattr(self.industry, "reply_hook", ""):
            hook_prompt = f"\n\n⚠️【核心要求】私信的结尾必须非常自然地带上这个钩子话术引导回复：{self.industry.reply_hook}"

        try:
            prompt = (
                REPLY_HEADER.format(role=self.industry.reply_tone, style=f"{self.industry.reply_style}。{tone}")
                + (f"{hints}\n" if hints else "")
                + f"对方评论: {comment_text}"
                + hook_prompt
                + REPLY_FOOTER
            )
            resp = _get_reply_client(getattr(self.industry, "deepseek_key", "")).chat.completions.create(
                model="deepseek-chat", messages=[{"role": "user", "content": prompt}],
                max_tokens=80, temperature=0.9,
            )
            return resp.choices[0].message.content.strip()[:60]
        except Exception:
            fallbacks = [
                f"你好，我是{self.industry.reply_tone}，看到你的评论，需要帮忙吗？",
                f"关于你问的，我比较了解，方便的话私聊。",
            ]
            return random.choice(fallbacks)

    def _init_agent_safe(self) -> bool:
        if self._executor:
            return True
        try:
            from core.adb_keyboard import prepare_adb_keyboard
            status = prepare_adb_keyboard(self.adb_serial, install_if_missing=True)
            if not status.get("ok"):
                log.error(f"[{self.device_id}] ADB Keyboard not ready")
                return False
                
            glm_base, glm_model, _, glm_key = _get_glm_config(getattr(self.industry, "zhipu_key", ""))
            self._executor = PhoneAgentExecutor(
                adb_serial=self.adb_serial,
                base_url=glm_base,
                model_name=glm_model,
                api_key=glm_key,
                should_stop=self.should_stop,
                max_steps=20,
            ).start()
            return True
        except Exception as e:
            log.error(f"[{self.device_id}] PhoneAgent init failed: {e}")
            return False

    def run(self):
        summary = {
            "device_id": self.device_id, "adb_serial": self.adb_serial,
            "industry_slug": self.industry_slug, "status": "running",
            "sent": 0, "failed": 0, "cancelled": False, "error": "",
            "daily_limit_reached": False, "global_limit_reached": False, "no_task": False
        }
        gate = self._supervisor.preflight(device_id=self.device_id, adb_serial=self.adb_serial, job_id=self.job_id)
        if not gate.ok:
            summary.update(status=gate.status, error=gate.reason)
            return summary

        try:
            while True:
                if self.should_stop and self.should_stop():
                    summary.update(status="cancelled", cancelled=True)
                    break
                    
                claim = self._scheduler.claim_for_device(self.device_id, min_interval_sec=self.min_interval)
                
                if not claim.ok:
                    if claim.reason == "device_daily_limit_reached":
                        summary.update(status="daily_limit", daily_limit_reached=True)
                    elif claim.reason == "global_daily_limit_reached":
                        summary.update(status="quota_reached", global_limit_reached=True)
                    elif claim.reason == "device_rate_limited":
                        # Simulate wait
                        time.sleep(30)
                        continue
                    else:
                        summary.update(status="no_task", no_task=True)
                    break

                task = claim.task
                reply_msg = self._generate_reply(task)
                short_id = task.get("source_short_id") or task.get("source_sec_uid") or ""
                
                if not self._init_agent_safe():
                    self._scheduler.commit_task(claim.task_id, self.device_id, "fail", "Agent init failed")
                    break

                try:
                    from core.agent.perception import PerceptionService
                    from core.task.runner import TaskGraphRunner

                    perception = PerceptionService()
                    runner = TaskGraphRunner(memory=self._memory, planner=self._planner, perception=perception)
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
                        self._scheduler.commit_task(claim.task_id, self.device_id, "done", "")
                        summary["sent"] += 1
                    else:
                        self._scheduler.commit_task(claim.task_id, self.device_id, "fail", exec_result.message[:500])
                        summary["failed"] += 1
                except Exception as e:
                    self._scheduler.commit_task(claim.task_id, self.device_id, "fail", str(e)[:500])
                    summary["failed"] += 1

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
                device_id=self.device_id, job_id=self.job_id,
                status=summary["status"] if summary["status"] not in ("running", "cancelled") else "idle"
            )

        return summary


def _run_device(d: dict, industry: IndustryConfig, should_stop=None, job_id: str = ""):
    try:
        worker = DeviceWorker(
            device_id=d["id"], adb_serial=d.get("adb_serial", ""),
            industry=industry, daily_limit=d.get("daily_limit", industry.daily_limit),
            min_interval=d.get("min_interval_sec", 90),
            should_stop=should_stop, job_id=job_id
        )
        return worker.run()
    except Exception as e:
        log.error(f"[{d['id']}] fatal: {e}")
        return {"device_id": d["id"], "status": "failed", "error": str(e)[:500]}

def run_senders(industry: IndustryConfig, device_ids: list[str] = None, should_stop=None, job_id: str = ""):
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
        log.info("Compliance mode enabled for %s; skipping actual send.", getattr(industry, "slug", ""))
        return {
            "ok": True,
            "skipped": True,
            "reason": "compliance_mode",
            "industry_slug": getattr(industry, "slug", ""),
            "message": "合规模式已开启，仅采集不发送。",
        }
    user_id = getattr(industry, "user_id", "") or ""
    requested_device_ids = [str(d).strip() for d in (device_ids or []) if str(d).strip()]
    targets = [
        device.as_sender_dict()
        for device in load_active_devices(user_id=user_id, device_ids=requested_device_ids)
    ]

    if not targets:
        return {"ok": False, "error": "no available devices", "devices_total": 0}

    # ── Try Celery first ──
    try:
        from adapters.celery.send import send_dm_task
        log.info("Using Celery backend for %d devices", len(targets))

        task_results = []
        for d in targets:
            # Submit one task per device — Celery handles concurrency + rate limiting
            async_result = send_dm_task.delay(
                device_id=d["id"],
                adb_serial=d.get("adb_serial", ""),
                industry_slug=getattr(industry, "slug", ""),
                task_data={
                    "industry_name": getattr(industry, "name", ""),
                    "reply_tone": getattr(industry, "reply_tone", ""),
                    "reply_style": getattr(industry, "reply_style", ""),
                    "daily_limit": d.get("daily_limit", 15),
                    "min_interval_sec": d.get("min_interval_sec", 90),
                    "user_id": user_id,
                },
                reply_msg="",  # Celery task generates reply itself
            )
            task_results.append({
                "device_id": d["id"],
                "task_id": async_result.id,
                "status": "dispatched",
            })

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

    for t in threads:
        t.join()

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
