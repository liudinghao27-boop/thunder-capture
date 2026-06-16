"""AutoGLM DM 发送引擎 — 多设备并行矩阵"""

import json
import time
import random
import logging
import threading
from openai import OpenAI

from .config import IndustryConfig, load_system
from .queue import (
    init as init_db, claim_task, mark_task_done, mark_task_failed,
    mark_task_retry, log_action, get_consumer_state, increment_consumer_sent,
    increment_consumer_failed, queue_stats, reclaim_stale_claims,
)

log = logging.getLogger("thunder.sender")

_reply_client = None
_loaded_reply_key = None


def _get_reply_client():
    global _reply_client, _loaded_reply_key
    sys_cfg = load_system()
    key = sys_cfg["api_keys"]["deepseek"]
    if _reply_client is None or key != _loaded_reply_key:
        import httpx
        _reply_client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        _loaded_reply_key = key
    return _reply_client


def _get_glm_config():
    sys_cfg = load_system()
    glm = sys_cfg["autoglm"]
    return glm["base_url"], glm["model"], sys_cfg["api_keys"]["zhipu"]

REPLY_HEADER = "你是{role}。{style}\n"
REPLY_FOOTER = "\n直接给回复文案(15-30字)，不要加微信/链接/emoji，不要解释。"

# Random tone variations to avoid reply repetition
TONE_VARIATIONS = [
    "语气要热情主动",
    "语气要稳重可靠",
    "语气要简洁专业",
    "语气要亲切自然",
    "语气要像个老大哥",
]


class DeviceSender:
    """单设备发送器（每个设备在独立线程中运行）"""

    def __init__(self, device_id: str, adb_serial: str,
                 industry: IndustryConfig, daily_limit: int = 15,
                 min_interval: int = 90):
        self.device_id = device_id
        self.adb_serial = adb_serial
        self.industry = industry
        self.daily_limit = daily_limit
        self.min_interval = min_interval
        self._agent = None

    def _generate_reply(self, task: dict) -> str:
        """Generate reply using DeepSeek, informed by LLM classification hints."""
        comment_text = task.get("text", "")
        question = ""
        reply_topic = ""

        # Extract LLM classification hints from matched_categories JSON
        try:
            raw = task.get("matched_categories", "[]")
            if raw and raw != "[]":
                meta = json.loads(raw)
                if isinstance(meta, dict):
                    question = meta.get("question", "")
                    reply_topic = meta.get("reply_topic", "")
        except (json.JSONDecodeError, TypeError):
            pass

        hints = ""
        if question:
            hints += f"用户问题：{question}。"
        if reply_topic:
            hints += f"回复方向：{reply_topic}。"

        tone = random.choice(TONE_VARIATIONS)

        try:
            prompt = (
                REPLY_HEADER.format(
                    role=self.industry.reply_tone,
                    style=f"{self.industry.reply_style}。{tone}",
                )
                + (f"{hints}\n" if hints else "")
                + f"对方评论: {comment_text}"
                + REPLY_FOOTER
            )
            resp = _get_reply_client().chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80, temperature=0.9,
            )
            return resp.choices[0].message.content.strip()[:60]
        except Exception:
            fallbacks = [
                f"你好，我是{self.industry.reply_tone}，看到你的评论，需要帮忙吗？",
                f"关于你问的，我比较了解，方便的话私聊。",
                f"我有这方面的经验，可以帮你看看。",
            ]
            return random.choice(fallbacks)

    def _check_adb_keyboard(self) -> bool:
        """Verify ADB Keyboard is available on the device."""
        import subprocess
        try:
            r = subprocess.run(
                ["adb", "-s", self.adb_serial, "shell",
                 "ime", "list", "-s"],
                capture_output=True, text=True, timeout=5,
            )
            output = r.stdout + r.stderr
            if "adbkeyboard" in output.lower():
                return True
            if "SecurityException" in output or "WRITE_SECURE_SETTINGS" in output:
                raise PermissionError("ime blocked")
        except (PermissionError, Exception):
            pass

        try:
            r = subprocess.run(
                ["adb", "-s", self.adb_serial, "shell",
                 "settings", "get", "secure", "default_input_method"],
                capture_output=True, text=True, timeout=5,
            )
            current = (r.stdout + r.stderr).strip()
            if "adbkeyboard" in current.lower():
                return True
        except Exception:
            pass

        try:
            r = subprocess.run(
                ["adb", "-s", self.adb_serial, "shell",
                 "pm", "list", "packages", "adbkeyboard"],
                capture_output=True, text=True, timeout=5,
            )
            if "adbkeyboard" in (r.stdout + r.stderr).lower():
                log.warning(f"  [{self.device_id}] ADB Keyboard installed but not active")
                log.warning(f"     Switch to ADB Keyboard manually then retry")
                return False
        except Exception:
            pass

        log.error(f"  [{self.device_id}] ADB Keyboard not installed!")
        return False

    def _init_agent(self):
        if not self._check_adb_keyboard():
            raise RuntimeError("ADB Keyboard required for Chinese input")

        from phone_agent import PhoneAgent
        from phone_agent.agent import AgentConfig
        from phone_agent.model import ModelConfig

        glm_base, glm_model, glm_key = _get_glm_config()
        model_cfg = ModelConfig(
            base_url=glm_base,
            model_name=glm_model,
            api_key=glm_key,
        )
        agent_cfg = AgentConfig(
            max_steps=20, lang="cn",
            device_id=self.adb_serial or None,
        )
        self._agent = PhoneAgent(model_config=model_cfg, agent_config=agent_cfg)
        log.info(f"  [{self.device_id}] PhoneAgent ready")

    def _init_agent_safe(self) -> bool:
        """Initialize agent with error handling. Returns True on success."""
        try:
            self._init_agent()
            return True
        except Exception as e:
            log.error(f"  [{self.device_id}] agent init failed: {e}")
            return False

    @staticmethod
    def _is_agent_crash(error: str) -> bool:
        """Check if the error indicates an agent-level crash (vs user not found etc)."""
        crash_markers = ["Connection error", "Model error", "Rate limit",
                        "timeout", "timed out", "connection", "AttributeError",
                        "TypeError", "KeyError", "NoneType"]
        error_lower = error.lower()
        return any(m.lower() in error_lower for m in crash_markers)

    def _send_dm(self, short_id: str, user_name: str, message: str) -> tuple:
        search_target = short_id or user_name
        id_hint = (
            f"目标用户抖音号: '{short_id}'，昵称: '{user_name}'。"
            f"必须以抖音号精确匹配为准。"
        ) if short_id else (
            f"目标用户昵称: '{user_name}'。"
        )

        task_text = (
            f"## 任务: 在抖音给目标用户发一条私信\n\n"
            f"消息内容: '{message}'\n"
            f"{id_hint}\n\n"
            f"### 执行步骤 — 每步完成后必须在屏幕截图上确认对应状态，确认无误再继续:\n\n"
            f"**步骤1: 打开抖音**\n"
            f"  - 确认屏幕出现抖音首页(底部导航栏有「首页」「朋友」「消息」「我」、推荐视频流可见)\n"
            f"  - 如下划离开了其他页面，按返回键回到首页\n\n"
            f"**步骤2: 搜索用户 '{search_target}'**\n"
            f"  - 点击顶部搜索框，输入'{search_target}'\n"
            f"  - 点击搜索结果页顶部 tab 栏中的「用户」标签\n"
            f"  - 确认屏幕显示用户列表，且搜索框中可见'{search_target}'\n"
            f"  - 如果搜索结果为空或用户标签页不可见，检查输入是否有误后重试\n\n"
            f"**步骤3: 找到目标用户并进入主页**\n"
            f"  - 在用户列表中逐一核对每个候选用户的抖音号字段\n"
            f"  - 如果列表里能看到完整的抖音号，只选择抖音号精确等于 '{search_target}' 的那个\n"
            f"  - 如果列表里看不到完整抖音号，点进第一个候选用户主页，核对主页顶部显示的抖音号\n"
            f"  - 如果主页抖音号不匹配，返回搜索结果继续尝试下一个候选\n"
            f"  - 确认: 进入主页后，主页顶部的抖音号/昵称与目标一致\n\n"
            f"**步骤4: 进入私信界面**\n"
            f"  - 在目标用户主页找到并点击「发私信」按钮\n"
            f"  - 如果主页上没有直接显示「发私信」，点击右上角三点菜单或「聊天」图标\n"
            f"  - 确认: 屏幕显示私信聊天界面，底部有文本输入框和发送按钮\n"
            f"  - 如果看到的是「关注」按钮而非「发私信」，说明对方设置了隐私限制，报告失败\n\n"
            f"**步骤5: 发送消息并确认**\n"
            f"  - 在输入框中输入消息: '{message}'\n"
            f"  - 点击发送按钮\n"
            f"  - 确认: 聊天界面中出现刚才发送的消息气泡(绿色或蓝色的对话框)\n"
            f"  - ⚠️ 看到消息气泡出现后立即停止，绝对不要重复发送\n"
            f"  - ⚠️ 如果发送后看不到气泡，说明发送失败，报告失败\n\n"
            f"### 全局规则:\n"
            f"  - 每一步必须在屏幕截图上确认目标状态已出现，才能进入下一步\n"
            f"  - 如果某个步骤尝试2次仍未到达目标状态，调整策略(如换入口、返回重来)\n"
            f"  - 完成后报告「任务完成」并说明每一步的确认结果"
        )
        try:
            result = self._agent.run(task_text)
            result_s = str(result).strip() if result else ""
            failure_markers = ["失败", "错误", "无法", "超时", "未找到",
                             "未发送", "不存在", "打不开", "找不到",
                             "Model error", "Connection error", "Rate limit"]
            success_markers = ["任务完成", "已成功", "消息已发送", "发送成功",
                             "操作成功", "成功发送"]

            if result_s:
                is_failure = any(m in result_s for m in failure_markers)
                if is_failure:
                    return False, result_s[:200]
                is_success = any(m in result_s for m in success_markers)
                if is_success:
                    return True, result_s[:200]
            return False, result_s[:200] if result_s else "empty result"
        except KeyboardInterrupt:
            raise
        except Exception as e:
            return False, str(e)[:500]

    def run(self):
        log.info(f"  [{self.device_id}] start: {self.daily_limit}/day")
        init_db()
        reclaim_stale_claims(1)

        state = get_consumer_state(self.device_id)
        sent = state["daily_sent"]
        if sent >= self.daily_limit:
            log.info(f"  [{self.device_id}] daily limit reached {sent}/{self.daily_limit}")
            return

        agent_ok = self._init_agent_safe()
        if not agent_ok:
            log.error(f"  [{self.device_id}] agent init failed — aborting")
            return

        consecutive_failures = 0
        while sent < self.daily_limit:
            state = get_consumer_state(self.device_id)
            sent = state["daily_sent"]
            if sent >= self.daily_limit:
                break

            task = claim_task(self.device_id)
            if not task:
                s = queue_stats()
                log.info(f"  [{self.device_id}] no pending tasks ({s['pending']} pending)")
                break

            user_name = task["user_name"]
            search_id = (task.get("unique_id", "") or
                        task.get("short_id", "") or
                        task.get("douyin_id", ""))
            if not search_id:
                log.warning(f"  [{self.device_id}] no douyin ID for #{task['id']} @{user_name}, "
                           f"falling back to username search (may be imprecise)")
            comment_text = task["text"]

            log.info(f"  [{self.device_id}] #{task['id']} @{user_name}")
            reply = self._generate_reply(task)
            log.info(f"  [{self.device_id}] reply: {reply}")

            success, error = self._send_dm(search_id, user_name, reply)

            # Agent crash → re-initialize and retry once
            if not success and self._is_agent_crash(error):
                log.warning(f"  [{self.device_id}] agent crash, re-initializing...")
                if self._init_agent_safe():
                    log.info(f"  [{self.device_id}] agent recovered, retrying send")
                    success, error = self._send_dm(search_id, user_name, reply)
                else:
                    log.error(f"  [{self.device_id}] agent re-init failed")

            if success:
                mark_task_done(task["id"], self.device_id, reply)
                increment_consumer_sent(self.device_id)
                log_action(self.device_id, task["id"], user_name, comment_text,
                          reply, "success")
                sent += 1
                consecutive_failures = 0
                log.info(f"  [{self.device_id}] [OK] #{task['id']} | {sent}/{self.daily_limit}")
            else:
                # User not found → retry later on different device
                if "not found" in error.lower() or "未找到" in error:
                    mark_task_retry(task["id"], self.device_id, error)
                    log.warning(f"  [{self.device_id}] [RETRY] #{task['id']}: user not found")
                else:
                    mark_task_failed(task["id"], self.device_id, error)
                    increment_consumer_failed(self.device_id)
                    log_action(self.device_id, task["id"], user_name, comment_text,
                              reply, "fail", error)
                    log.error(f"  [{self.device_id}] [FAIL] #{task['id']}: {error[:100]}")
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    log.error(f"  [{self.device_id}] {consecutive_failures} consecutive failures, aborting")
                    break

            if sent < self.daily_limit:
                wait = self.min_interval + random.randint(0, 30)
                log.info(f"  [{self.device_id}] wait {wait}s")
                time.sleep(wait)

        log.info(f"  [{self.device_id}] done: {sent}/{self.daily_limit}")


def _run_device(d: dict, industry: IndustryConfig):
    """Thread target: run sender on one device."""
    try:
        sender = DeviceSender(
            device_id=d["id"],
            adb_serial=d.get("adb_serial", ""),
            industry=industry,
            daily_limit=d.get("daily_limit", industry.daily_limit),
            min_interval=d.get("min_interval_sec", 90),
        )
        sender.run()
    except Exception as e:
        log.error(f"[{d['id']}] fatal: {e}")


def run_senders(industry: IndustryConfig, device_ids: list[str] = None):
    """Launch senders on all target devices in parallel threads."""
    all_devices = load_system().get("devices", [])
    targets = [d for d in all_devices
               if device_ids is None or d["id"] in device_ids]

    if not targets:
        log.error("no available devices")
        return

    log.info(f"parallel launch {len(targets)} devices: {[d['id'] for d in targets]}")

    threads = []
    for d in targets:
        t = threading.Thread(target=_run_device, args=(d, industry),
                           name=f"sender-{d['id']}", daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
