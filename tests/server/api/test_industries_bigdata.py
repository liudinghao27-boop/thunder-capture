"""Tests for server.api.industries big-data config endpoint."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from server.api import industries as industries_module
from server.api.industries import generate_industry_config_bigdata


def _user_without_keys():
    return SimpleNamespace(id="user-1", deepseek_key="", zhipu_key="", openai_key="")


@pytest.mark.asyncio
async def test_generate_config_bigdata_returns_usable_config_without_collector(
    monkeypatch,
):
    """Big-data config generation should not block project setup when collector is unavailable."""
    req = MagicMock()
    req.description = "军考培训，帮助士兵提升文化课成绩"
    req.seed_keyword = "军考"
    current_user = _user_without_keys()

    async def fake_collect(seed_keyword: str) -> dict:
        raise RuntimeError("collector unavailable")

    monkeypatch.setattr(
        industries_module, "_collect_douyin_bigdata_text_pool", fake_collect
    )

    result = await generate_industry_config_bigdata(req, current_user)

    assert result["bigdata_used"] is False
    assert result["name"]
    assert result["slug"].startswith("ind-")
    assert result["slug"] != "industry"
    assert "军考" in result["keywords"]
    assert result["reply_tone"]
    assert result["reply_style"]
    assert result["categories"]
    assert result["target_users"] == []
    assert result["llm_provider"] == "deepseek"
    assert result["llm_model"] == "deepseek-v4-flash"
    assert "尚未启用" not in result["bigdata_note"]


@pytest.mark.asyncio
async def test_generate_config_bigdata_uses_collected_text_pool_and_llm(monkeypatch):
    """When Douyin big-data collection returns text, the endpoint should use it for AI generation."""
    req = MagicMock()
    req.description = "军考培训，帮助士兵提升文化课成绩"
    req.seed_keyword = "军考"
    captured = {}

    async def fake_collect(seed_keyword: str, user_id: str = "") -> dict:
        captured["seed_keyword"] = seed_keyword
        captured["user_id"] = user_id
        return {
            "sample_count": 2,
            "texts": [
                "军考英语怎么补基础",
                "士兵文化课提分有没有靠谱课程",
            ],
        }

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured["messages"] = kwargs["messages"]
                    content = {
                        "name": "军考提分",
                        "slug": "military-exam",
                        "keywords": ["军考英语基础", "士兵文化课提分"],
                        "intent_keywords": ["军考怎么报名", "文化课怎么提分"],
                        "noise_keywords": ["路过"],
                        "reply_tone": "军考规划顾问",
                        "reply_style": "先确认基础，再给备考建议",
                        "reply_hook": "可以先帮你整理一份军考提分方案。",
                        "categories": ["军考咨询", "文化课提分"],
                        "target_users": ["MS4w-target"],
                    }
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content=json.dumps(content, ensure_ascii=False)
                                )
                            )
                        ]
                    )

    monkeypatch.setattr(
        industries_module,
        "_collect_douyin_bigdata_text_pool",
        fake_collect,
        raising=False,
    )
    monkeypatch.setattr(
        "server.services.llm.get_llm_client",
        lambda **kwargs: FakeClient(),
    )

    result = await generate_industry_config_bigdata(req, _user_without_keys())

    assert captured["seed_keyword"] == "军考"
    user_prompt = captured["messages"][1]["content"]
    assert "军考英语怎么补基础" in user_prompt
    assert result["bigdata_used"] is True
    assert result["bigdata_sample_count"] == 2
    assert result["keywords"] == ["军考英语基础", "士兵文化课提分"]
