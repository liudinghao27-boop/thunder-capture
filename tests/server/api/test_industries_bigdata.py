"""Tests for server.api.industries big-data config endpoint."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from server.api.industries import generate_industry_config_bigdata


@pytest.mark.asyncio
async def test_generate_config_bigdata_returns_501():
    """Big-data config generation endpoint should return 501 until implemented."""
    req = MagicMock()
    req.description = "test"
    req.seed_keyword = "test"
    current_user = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await generate_industry_config_bigdata(req, current_user)

    assert exc_info.value.status_code == 501
