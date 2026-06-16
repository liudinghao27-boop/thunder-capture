"""LLM 意图分类 — 行业感知"""

import json
import re
import logging
from openai import OpenAI

from .config import IndustryConfig, load_system
from .queue import enqueue_task

log = logging.getLogger("thunder.classify")

# Regex pre-filter: only send comments matching intent patterns to LLM
_INTENT_PATTERNS = [
    r"[问吗呢嘛]",
    r"可以|行吗|能不能|可不可以|是否可以",
    r"怎么|如何|怎样|咋",
    r"好不好|行不行|有没有|会不会|要不要",
    r"怎么办|咋办|怎么办呀",
    r"求[教助问帮]|帮[帮我忙]|麻烦|请教",
    r"推荐|建议|介绍|分享|告知",
    r"想[要去学知道参加了解]|打算|准备|计划",
    r"报名|申请|流程|条件|要求|标准",
    r"请问|问下|咨询|了解下|想了解",
]
_NOISE_PATTERNS = [
    r"^[哈嘿嘻呵嗯哦啊哇]+$",
    r"^(加油|支持|顶|赞|666+|牛逼|牛比|太牛|真牛|好帅|太棒|爱了|喜欢|好看)+$",
    r"^(沙发|第一|来了|打卡|前排|留名|路过)+$",
]
_intent_re = re.compile("|".join(_INTENT_PATTERNS))
_noise_re = re.compile("|".join(_NOISE_PATTERNS))


def prefilter_comments(comments: list[dict], intent_words=None, noise_words=None) -> tuple[list[dict], list[dict]]:
    """Fast regex pre-filter. Returns (passed, skipped). Accepts custom word lists."""
    import re as _re
    if intent_words:
        intent_re = _re.compile("|".join(intent_words))
    else:
        intent_re = _intent_re
    if noise_words:
        noise_re = _re.compile("|".join(noise_words))
    else:
        noise_re = _noise_re

    passed, skipped = [], []
    for c in comments:
        text = c.get("content", "").strip()
        if len(text) < 4:
            skipped.append(c)
            continue
        if noise_re.match(text):
            skipped.append(c)
            continue
        if intent_re.search(text):
            passed.append(c)
        else:
            skipped.append(c)
    return passed, skipped
_client = None
_loaded_key = None


def _get_client():
    global _client, _loaded_key
    sys_cfg = load_system()
    key = sys_cfg["api_keys"]["deepseek"]
    if _client is None or key != _loaded_key:
        import httpx
        _client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        _loaded_key = key
    return _client

BATCH_CLASSIFY_HEADER = """你是{industry}的{role}。分析以下{count}条抖音评论，判断每条是否来自潜在客户。

行业背景: {industry} - {categories}

评论列表:
"""

BATCH_CLASSIFY_FOOTER = """
请返回一个JSON数组，每个元素对应一条评论的分析结果：
[{{"index":0,"is_target":true/false,"confidence":"high/medium/low","category":"{categories_str}","question":"用户具体问题","suggested_reply_topic":"建议回复方向"}},
 {{"index":1,...}},
 ...]
只输出JSON数组，不要其他内容。"""

BATCH_SIZE = 10


def classify_batch(comments: list[dict], industry: IndustryConfig,
                   llm_client=None, intent_words=None, noise_words=None) -> list[dict]:
    """Pre-filter + batched LLM classify. Returns comments that pass both."""
    passed = []
    total = len(comments)
    if not total:
        return passed

    # Step 1: regex pre-filter
    candidates, skipped = prefilter_comments(comments, intent_words, noise_words)
    log.info(f"  意图预筛: {len(candidates)}/{total} 进入 LLM ({len(skipped)} 跳过)")

    if not candidates:
        return passed

    # Step 2: batch LLM classification
    client = llm_client or _get_client()
    batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE
    log.info(f"  LLM 批量分类 {len(candidates)} 条 → {batches} 批")

    for batch_num in range(batches):
        start = batch_num * BATCH_SIZE
        chunk = candidates[start:start + BATCH_SIZE]

        comment_list = "\n".join(
            f"[{i}] {c.get('content', '').strip()}" for i, c in enumerate(chunk)
        )

        try:
            header = BATCH_CLASSIFY_HEADER.format(
                industry=industry.name,
                role=industry.reply_tone,
                count=len(chunk),
                categories=", ".join(industry.categories),
            )
            footer = BATCH_CLASSIFY_FOOTER.format(
                categories_str=", ".join(industry.categories),
            )
            prompt = header + comment_list + footer

            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.1,
            )

            result = resp.choices[0].message.content.strip()
            result = result.replace("```json", "").replace("```", "").strip()

            batch_data = json.loads(result)
            if not isinstance(batch_data, list):
                batch_data = [batch_data]

            for item in batch_data:
                idx = item.get("index", -1)
                if 0 <= idx < len(chunk) and item.get("is_target"):
                    c = chunk[idx]
                    c["matched_categories"] = json.dumps({
                        "categories": [item.get("category", "")],
                        "question": item.get("question", ""),
                        "reply_topic": item.get("suggested_reply_topic", ""),
                    }, ensure_ascii=False)
                    c["_llm_question"] = item.get("question", "")
                    c["_llm_reply_topic"] = item.get("suggested_reply_topic", "")
                    passed.append(c)

        except Exception as e:
            log.warning(f"    批量分类异常 (batch {batch_num + 1}): {e}")
            # Fallback: skip batch on error
            continue

        log.info(f"    进度: {min(start + BATCH_SIZE, len(candidates))}/{len(candidates)}")

    log.info(f"  LLM 通过: {len(passed)}/{len(candidates)} (总入队 {len(passed)}/{total})")
    return passed


def enqueue_classified(comments: list[dict]):
    """将分类通过的评论写入任务队列"""
    count = 0
    for c in comments:
        if enqueue_task(c):
            count += 1
    log.info(f"  入队: {count} 条")
    return count
