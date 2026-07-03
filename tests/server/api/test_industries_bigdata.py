"""Tests for server.api.industries big-data config endpoint."""

from unittest.mock import MagicMock

import pytest
from server.api.industries import generate_industry_config_bigdata


@pytest.mark.asyncio
async def test_generate_config_bigdata_returns_usable_config_without_collector():
    """Big-data config generation should not block project setup when collector is unavailable."""
    req = MagicMock()
    req.description = "军考培训，帮助士兵提升文化课成绩"
    req.seed_keyword = "军考"
    current_user = MagicMock()

    result = await generate_industry_config_bigdata(req, current_user)

    assert result["bigdata_used"] is False
    assert result["name"]
    assert result["slug"].startswith("ind-")
    assert result["slug"] != "industry"
    assert "军考" in result["keywords"]
    assert result["reply_tone"]
    assert result["reply_style"]
    assert result["categories"]
    assert result["llm_provider"] == "deepseek"
    assert result["llm_model"] == "deepseek-v4-flash"
