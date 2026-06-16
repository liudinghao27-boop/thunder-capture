"""Industry schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class IndustryCreate(BaseModel):
    name: str
    slug: str
    keywords: list[str] = []
    platforms: list[str] = ["douyin"]
    reply_tone: str = "业内人士"
    reply_style: str = "亲切专业"
    categories: list[str] = []
    daily_limit: int = 15
    video_max_age_days: int = 14
    comment_max_age_hours: int = 48
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    intent_keywords: list[str] = []
    noise_keywords: list[str] = []


class IndustryUpdate(BaseModel):
    name: Optional[str] = None
    keywords: Optional[list[str]] = None
    platforms: Optional[list[str]] = None
    reply_tone: Optional[str] = None
    reply_style: Optional[str] = None
    categories: Optional[list[str]] = None
    daily_limit: Optional[int] = None
    video_max_age_days: Optional[int] = None
    comment_max_age_hours: Optional[int] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    intent_keywords: Optional[list[str]] = None
    noise_keywords: Optional[list[str]] = None
    is_active: Optional[bool] = None


class IndustryOut(BaseModel):
    id: str
    user_id: str
    name: str
    slug: str
    keywords: list
    platforms: list
    reply_tone: str
    reply_style: str
    categories: list
    daily_limit: int
    video_max_age_days: int
    comment_max_age_hours: int
    llm_provider: str
    llm_model: str
    intent_keywords: list
    noise_keywords: list
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class IndustryStats(BaseModel):
    total_tasks: int = 0
    pending: int = 0
    done: int = 0
    failed: int = 0
    active_bloggers: int = 0
    success_rate: float = 0.0
