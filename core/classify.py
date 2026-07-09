"""Intent classification for collected social comments.

Architecture (v0.2 — Dify-ready):
    classify_batch()
        ├── prefilter_comments()        ← regex (deterministic, always first)
        ├── ClassificationRouter        ← auto-detect backend
        │   ├── DifyBackend             ← if DIFY_API_URL is set
        │   └── DirectLLMBackend        ← fallback: DeepSeek API
        └── _apply_classification()     ← attach results to comment dicts
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

import json_repair

from .config import IndustryConfig
from server.services.task_stats import enqueue_tasks_batch, enqueue_tasks_batch_result

log = logging.getLogger("thunder.classify")


_DEFAULT_INTENT_PATTERNS = [
    r"[？?]",
    r"请问|问下|咨询|了解|想了解|求问|求助|请教|麻烦问",
    r"怎么|如何|咋办|怎么办|怎样|哪里|哪家|哪个|有没有",
    r"可以吗|行吗|能不能|可不可以|是否可以|适合吗|靠谱吗",
    r"多少钱|费用|价格|报价|预算|贵不贵|收费",
    r"条件|要求|流程|标准|政策|材料|资料|方案",
    r"报名|申请|预约|推荐|建议|介绍|对接|联系",
    r"想要|需要|准备|打算|计划|考虑|正在找|有没有人",
]

_DEFAULT_NOISE_PATTERNS = [
    r"^[哈啊嗯哦哇哎]+$",
    r"^(加油|支持|点赞|666+|牛|太牛了|真牛|好帅|太棒了|喜欢|好看|收藏|转发)$",
    r"^(沙发|第一|来了|打卡|前排|留名|路过|占个位置)$",
    r"^(哈哈哈+|笑死|离谱|绝了|泪目)$",
]

_STRONG_INTENT_RE = re.compile("|".join(_DEFAULT_INTENT_PATTERNS))
_NOISE_RE = re.compile("|".join(_DEFAULT_NOISE_PATTERNS))


def _comment_text(comment: dict) -> str:
    return str(comment.get("content") or comment.get("text") or "").strip()


def _compile_word_pattern(words: tuple[str, ...]) -> str:
    clean = [w.strip() for w in words if str(w).strip()]
    return "|".join(re.escape(w) for w in clean)


@lru_cache(maxsize=64)
def _compile_patterns(
    intent_words: tuple[str, ...] = (), noise_words: tuple[str, ...] = ()
) -> tuple[re.Pattern, re.Pattern]:
    intent_parts = list(_DEFAULT_INTENT_PATTERNS)
    custom_intent = _compile_word_pattern(intent_words)
    if custom_intent:
        intent_parts.append(custom_intent)

    noise_parts = list(_DEFAULT_NOISE_PATTERNS)
    custom_noise = _compile_word_pattern(noise_words)
    if custom_noise:
        noise_parts.append(custom_noise)

    return re.compile("|".join(intent_parts)), re.compile("|".join(noise_parts))


def prefilter_comments(
    comments: list[dict], intent_words=None, noise_words=None
) -> tuple[list[dict], list[dict]]:
    """Fast deterministic filter before AI classification."""
    intent_tuple = tuple(intent_words or ())
    noise_tuple = tuple(noise_words or ())
    intent_re, noise_re = _compile_patterns(intent_tuple, noise_tuple)

    passed, skipped = [], []
    for comment in comments:
        text = _comment_text(comment)
        if len(text) < 2:
            skipped.append(comment)
            continue
        if noise_re.search(text):
            skipped.append(comment)
            continue
        if intent_re.search(text):
            passed.append(comment)
        else:
            skipped.append(comment)
    return passed, skipped


# ═══════════════════════════════════════════════════════════
#  Classification Backend Abstraction
# ═══════════════════════════════════════════════════════════


@dataclass
class ClassifiedComment:
    """Backend-agnostic classification result for one comment."""

    index: int
    is_target: bool
    confidence: str  # high / medium / low
    category: str
    question: str
    suggested_reply_topic: str
    evidence: str


class ClassificationBackend(ABC):
    """Abstract backend for comment classification.

    Implementations:
      - DirectLLMBackend  — DeepSeek API with hardcoded prompts
      - DifyBackend        — Dify workflow API
    """

    @abstractmethod
    def classify(
        self,
        candidates: list[dict],
        industry: IndustryConfig,
        categories: list[str],
        *,
        progress_callback=None,
    ) -> list[ClassifiedComment]:
        """Classify prefiltered candidate comments."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name for logging."""
        ...


# ═══════════════════════════════════════════════════════════
#  Backend: Direct LLM (DeepSeek) — legacy, always available
# ═══════════════════════════════════════════════════════════

_BATCH_CLASSIFY_HEADER = """你是{industry}行业的线索质检员，需要判断评论是否来自潜在客户。

只把"正在咨询、求方案、求价格、求条件、求推荐、准备行动"的评论判为目标线索。
以下内容必须判为非目标：夸赞、玩笑、路过、情绪表达、同行广告、泛泛讨论、没有明确需求的问题。

行业名称：{industry}
行业服务分类：{categories}

请分析下面 {count} 条评论：
"""

_BATCH_CLASSIFY_FOOTER = """

返回 JSON 数组，数组长度可以小于输入数量，但每个对象必须对应原 index：
[
  {
    "index": 0,
    "is_target": true,
    "confidence": "high",
    "category": "分类名称",
    "question": "用户明确想解决的问题",
    "suggested_reply_topic": "后续回复方向",
    "evidence": "为什么这是明确意向"
  }
]

规则：
1. confidence 只能是 high、medium、low。
2. 只有评论本身有明确需求、咨询或行动信号，才允许 is_target=true。
3. 仅仅出现行业关键词，但没有需求表达，必须 is_target=false。
4. 不确定时设置 is_target=false。
5. 只输出 JSON，不要输出解释。
"""

BATCH_SIZE = 10
_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _min_confidence() -> str:
    configured = os.getenv("THUNDER_CLASSIFY_MIN_CONFIDENCE", "high").strip().lower()
    return configured if configured in _CONFIDENCE_ORDER else "high"


class DirectLLMBackend(ClassificationBackend):
    """Direct DeepSeek API classification (legacy path, always available)."""

    name = "DirectLLM (DeepSeek)"

    def __init__(self, llm_client=None):
        self._client = llm_client

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from server.services.llm import get_deepseek_client

            self._client = get_deepseek_client()
            return self._client
        except ImportError:
            pass
        try:
            import httpx
            from openai import OpenAI
            from core.config import load_system

            cfg = load_system()
            self._client = OpenAI(
                base_url="https://api.deepseek.com",
                api_key=cfg["api_keys"]["deepseek"],
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            return self._client
        except Exception:
            raise

    def classify(
        self,
        candidates: list[dict],
        industry: IndustryConfig,
        categories: list[str],
        *,
        progress_callback=None,
    ) -> list[ClassifiedComment]:
        client = self._ensure_client()
        results: list[ClassifiedComment] = []
        batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num in range(batches):
            start = batch_num * BATCH_SIZE
            chunk = candidates[start : start + BATCH_SIZE]
            comment_list = "\n".join(
                (
                    f"[{i}] 评论: {_comment_text(comment)}\n"
                    f"    昵称: {comment.get('nickname') or comment.get('user_name') or ''}; "
                    f"来源: {comment.get('keyword', '')}; "
                    f"视频描述: {comment.get('source_video_desc', '')[:160]}"
                )
                for i, comment in enumerate(chunk)
            )

            try:
                prompt = (
                    _BATCH_CLASSIFY_HEADER.format(
                        industry=industry.name,
                        count=len(chunk),
                        categories=", ".join(categories),
                    )
                    + comment_list
                    + _BATCH_CLASSIFY_FOOTER
                )
                resp = client.chat.completions.create(
                    model=getattr(industry, "llm_model", "deepseek-v4-flash"),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2048,
                    temperature=0,
                )

                raw = resp.choices[0].message.content.strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                try:
                    batch_data = json.loads(raw)
                except json.JSONDecodeError:
                    batch_data = json_repair.loads(raw)

                if not isinstance(batch_data, list):
                    batch_data = [batch_data]

                for item in batch_data:
                    if not isinstance(item, dict):
                        continue
                    idx = item.get("index", -1)
                    if not isinstance(idx, int) or not (0 <= idx < len(chunk)):
                        continue
                    classified = ClassifiedComment(
                        index=start + idx,
                        is_target=bool(item.get("is_target", False)),
                        confidence=str(item.get("confidence", "low")).lower(),
                        category=str(item.get("category", "")),
                        question=str(item.get("question", "")),
                        suggested_reply_topic=str(
                            item.get("suggested_reply_topic", "")
                        ),
                        evidence=str(item.get("evidence", "")),
                    )
                    if classified.is_target:
                        results.append(classified)

            except Exception as exc:
                log.warning(
                    "DirectLLM batch %d/%d failed: %s", batch_num + 1, batches, exc
                )
                continue

            if progress_callback:
                progress_callback(batch_num + 1, batches)

        return results


# ═══════════════════════════════════════════════════════════
#  Backend: Dify Workflow
# ═══════════════════════════════════════════════════════════


class DifyBackend(ClassificationBackend):
    """Dify Workflow API classification backend.

    Auto-configured from DIFY_API_URL / DIFY_API_KEY env vars.
    Falls back gracefully: if Dify is unreachable, returns empty
    and ClassificationRouter switches to DirectLLMBackend.
    """

    name = "Dify Workflow"

    def __init__(self):
        self._client = None

    @property
    def available(self) -> bool:
        try:
            from adapters.dify.client import DifyClient

            client = DifyClient()
            return client.available
        except Exception:
            return False

    def _get_client(self):
        if self._client is None:
            from adapters.dify.client import DifyClient

            self._client = DifyClient()
        return self._client

    def classify(
        self,
        candidates: list[dict],
        industry: IndustryConfig,
        categories: list[str],
        *,
        progress_callback=None,
    ) -> list[ClassifiedComment]:
        if not self.available:
            return []

        try:
            client = self._get_client()
            dify_results = client.classify(
                comments=candidates,
                industry_name=industry.name,
                categories=categories,
                progress_callback=progress_callback,
            )
            return [
                ClassifiedComment(
                    index=r.index,
                    is_target=r.is_target,
                    confidence=r.confidence,
                    category=r.category,
                    question=r.question,
                    suggested_reply_topic=r.suggested_reply_topic,
                    evidence=r.evidence,
                )
                for r in dify_results
            ]
        except Exception as exc:
            log.error("Dify backend failed: %s — falling back to DirectLLM", exc)
            return []


# ═══════════════════════════════════════════════════════════
#  Classification Router — auto-detect which backend to use
# ═══════════════════════════════════════════════════════════


class ClassificationRouter:
    """Auto-detecting classification router.

    Priority:
      1. DifyBackend (if DIFY_API_URL is configured)
      2. DirectLLMBackend (always available fallback)
    """

    def __init__(self, llm_client=None):
        self._dify: DifyBackend | None = None
        self._direct: DirectLLMBackend | None = None
        self._direct_llm_client = llm_client

    @property
    def active_backend(self) -> ClassificationBackend:
        """Return the best available classification backend."""
        if self._dify is None:
            self._dify = DifyBackend()
        if self._dify.available:
            return self._dify

        if self._direct is None:
            self._direct = DirectLLMBackend(llm_client=self._direct_llm_client)
        return self._direct

    def classify(
        self,
        candidates: list[dict],
        industry: IndustryConfig,
        categories: list[str],
        *,
        progress_callback=None,
    ) -> list[ClassifiedComment]:
        backend = self.active_backend
        log.info("  分类后端: %s", backend.name)
        return backend.classify(
            candidates=candidates,
            industry=industry,
            categories=categories,
            progress_callback=progress_callback,
        )


# ═══════════════════════════════════════════════════════════
#  Quality gate — shared across all backends
# ═══════════════════════════════════════════════════════════


def _passes_quality_gate(item: ClassifiedComment, comment: dict) -> bool:
    """Filter classification results by confidence threshold."""
    if not item.is_target:
        return False
    confidence = item.confidence

    min_conf = _min_confidence()
    if _CONFIDENCE_ORDER.get(confidence, -1) >= _CONFIDENCE_ORDER[min_conf]:
        return True

    if confidence == "medium" and min_conf == "high":
        text = _comment_text(comment)
        question = item.question.strip()
        return bool(question and _STRONG_INTENT_RE.search(text))

    return False


def _attach_classification(comment: dict, item: ClassifiedComment) -> dict:
    """Attach classification metadata to a comment dict (mutates in-place)."""
    comment["matched_categories"] = json.dumps(
        {
            "categories": [item.category],
            "confidence": item.confidence,
            "question": item.question,
            "reply_topic": item.suggested_reply_topic,
            "evidence": item.evidence,
        },
        ensure_ascii=False,
    )
    comment["_llm_question"] = item.question
    comment["_llm_reply_topic"] = item.suggested_reply_topic
    return comment


# ═══════════════════════════════════════════════════════════
#  Main public API (backward-compatible)
# ═══════════════════════════════════════════════════════════

_router: ClassificationRouter | None = None


def classify_batch(
    comments: list[dict],
    industry: IndustryConfig,
    llm_client=None,
    intent_words=None,
    noise_words=None,
    progress_callback=None,
) -> list[dict]:
    """Filter comments through regex prefilter + AI classification.

    Backward-compatible signature. Internally uses ClassificationRouter
    to auto-select Dify (if configured) or DirectLLM (fallback).

    Returns: list of comment dicts with matched_categories/_llm_question/_llm_reply_topic attached.
    """
    global _router

    passed: list[dict] = []
    total = len(comments)
    if not total:
        return passed

    # Default categories
    categories = list(getattr(industry, "categories", []) or [])
    if not categories:
        categories = ["咨询类", "意向明确类", "条件确认类", "其他"]

    # ── Stage 1: Regex prefilter (always) ──
    candidates, skipped = prefilter_comments(comments, intent_words, noise_words)
    log.info(
        "  意向预筛: %s/%s 进入 AI (%s 跳过)", len(candidates), total, len(skipped)
    )
    if not candidates:
        return passed

    # ── Stage 2: AI classification (Dify or DirectLLM) ──
    if _router is None:
        _router = ClassificationRouter(llm_client=llm_client)

    try:
        classified = _router.classify(
            candidates=candidates,
            industry=industry,
            categories=categories,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        log.error("分类失败: %s", exc)
        return passed

    # ── Stage 3: Quality gate + attach metadata ──
    for item in classified:
        if item.index < 0 or item.index >= len(candidates):
            continue
        comment = candidates[item.index]

        if not _passes_quality_gate(item, comment):
            continue

        _attach_classification(comment, item)
        passed.append(comment)

    log.info(
        "  AI 通过: %s/%s (总入队候选 %s/%s) [via %s]",
        len(passed),
        len(candidates),
        len(passed),
        total,
        _router.active_backend.name,
    )
    return passed


def enqueue_classified(comments: list[dict]):
    """Write classified target comments into the sending queue."""
    normalized = []
    for comment in comments:
        matched = comment.get("matched_categories", {})
        if isinstance(matched, dict):
            comment = dict(comment)
            comment["matched_categories"] = json.dumps(matched, ensure_ascii=False)
        normalized.append(comment)
    count = enqueue_tasks_batch(normalized)
    log.info("  入队: %s 条", count)
    return count


def enqueue_classified_result(comments: list[dict]) -> dict:
    """Write classified target comments into the queue and return funnel metrics."""
    normalized = []
    for comment in comments:
        matched = comment.get("matched_categories", {})
        if isinstance(matched, dict):
            comment = dict(comment)
            comment["matched_categories"] = json.dumps(matched, ensure_ascii=False)
        normalized.append(comment)
    result = enqueue_tasks_batch_result(normalized)
    log.info(
        "  入队: %s 条(去重 %s)", result.get("inserted", 0), result.get("duplicates", 0)
    )
    return result
