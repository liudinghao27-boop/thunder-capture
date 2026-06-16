"""Industry schemas."""

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


SUPPORTED_PLATFORMS = {
    "douyin",
    "kuaishou",
    "wechat_channels",
    "xiaohongshu",
    "tiktok",
    "instagram",
    "facebook",
    "twitter",
    "youtube",
    "reddit",
}


def validate_single_platform(value: list[str] | None) -> list[str] | None:
    if value is None:
        return value
    platforms = [str(p).strip() for p in value if str(p).strip()]
    if not platforms:
        raise ValueError("请至少选择一个采集平台")
    if len(platforms) > 1:
        raise ValueError("采集平台只能单独选择，不能同时选择多个平台")
    if platforms[0] not in SUPPORTED_PLATFORMS:
        raise ValueError(f"不支持的采集平台: {platforms[0]}")
    return platforms


def normalize_unique_strings(value: list[str] | None) -> list[str] | None:
    if value is None:
        return value
    seen = set()
    result = []
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


class IndustryCreate(BaseModel):
    name: str
    slug: str
    keywords: list[str] = []
    platforms: list[str] = ["douyin"]
    reply_tone: str = "业内人士"
    reply_style: str = "亲切专业"
    reply_hook: str = ""
    categories: list[str] = []
    daily_limit: int = 15
    video_max_age_days: int = 14
    comment_max_age_hours: int = 48
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    intent_keywords: list[str] = []
    noise_keywords: list[str] = []
    target_users: list[str] = []
    matrix_target_devices: int = 30
    lead_inventory_days: int = 3
    global_daily_limit: int = 0
    auto_replenish_enabled: bool = False
    replenish_threshold_days: int = 1
    keyword_batch_size: int = 12
    collect_authors_per_run: int = 60
    collect_video_limit: int = 120
    compliance_mode: bool = False
    webhook_url: str = ""
    auto_export_enabled: bool = False
    send_start_time: str = "09:00"
    send_end_time: str = "13:00"
    pause_weekends: bool = False
    daily_send_max: int = 0
    effect_webhook_url: str = ""
    reply_variants: list[dict] = []

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, value: list[str]) -> list[str]:
        return validate_single_platform(value) or ["douyin"]

    @field_validator("intent_keywords", "noise_keywords", "target_users", "categories")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        return normalize_unique_strings(value) or []

    @field_validator("webhook_url")
    @classmethod
    def _validate_webhook_url(cls, value: str) -> str:
        if value and not re.match(r"^https?://\S+$", value):
            raise ValueError("webhook_url must be a valid HTTP/HTTPS URL")
        return value


class IndustryUpdate(BaseModel):
    name: Optional[str] = None
    keywords: Optional[list[str]] = None
    platforms: Optional[list[str]] = None
    reply_tone: Optional[str] = None
    reply_style: Optional[str] = None
    reply_hook: Optional[str] = None
    categories: Optional[list[str]] = None
    daily_limit: Optional[int] = None
    video_max_age_days: Optional[int] = None
    comment_max_age_hours: Optional[int] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    intent_keywords: Optional[list[str]] = None
    noise_keywords: Optional[list[str]] = None
    target_users: Optional[list[str]] = None
    matrix_target_devices: Optional[int] = None
    lead_inventory_days: Optional[int] = None
    global_daily_limit: Optional[int] = None
    auto_replenish_enabled: Optional[bool] = None
    replenish_threshold_days: Optional[int] = None
    keyword_batch_size: Optional[int] = None
    collect_authors_per_run: Optional[int] = None
    collect_video_limit: Optional[int] = None
    compliance_mode: Optional[bool] = None
    webhook_url: Optional[str] = None
    auto_export_enabled: Optional[bool] = None
    send_start_time: str | None = None
    send_end_time: str | None = None
    pause_weekends: bool | None = None
    daily_send_max: int | None = None
    effect_webhook_url: str | None = None
    reply_variants: list[dict] | None = None
    is_active: Optional[bool] = None

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return validate_single_platform(value)

    @field_validator("intent_keywords", "noise_keywords", "target_users", "categories")
    @classmethod
    def _normalize_string_list(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return normalize_unique_strings(value)

    @field_validator("webhook_url")
    @classmethod
    def _validate_webhook_url(cls, value: Optional[str]) -> Optional[str]:
        if value and not re.match(r"^https?://\S+$", value):
            raise ValueError("webhook_url must be a valid HTTP/HTTPS URL")
        return value


class IndustryOut(BaseModel):
    id: str
    user_id: str
    name: str
    slug: str
    keywords: list
    platforms: list
    reply_tone: str
    reply_style: str
    reply_hook: str = ""
    categories: list
    daily_limit: int
    video_max_age_days: int
    comment_max_age_hours: int
    llm_provider: str
    llm_model: str
    intent_keywords: list
    noise_keywords: list
    target_users: list[str] = []
    matrix_target_devices: int = 30
    lead_inventory_days: int = 3
    global_daily_limit: int = 0
    auto_replenish_enabled: bool = False
    replenish_threshold_days: int = 1
    keyword_batch_size: int = 12
    collect_authors_per_run: int = 60
    collect_video_limit: int = 120
    compliance_mode: bool = False
    webhook_url: str = ""
    auto_export_enabled: bool = False
    send_start_time: str = "09:00"
    send_end_time: str = "13:00"
    pause_weekends: bool = False
    daily_send_max: int = 0
    effect_webhook_url: str = ""
    reply_variants: list[dict] = []
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
    active_devices: int = 0
    matrix_target_devices: int = 30
    daily_send_capacity: int = 0
    global_daily_limit: int = 0
    global_sent_today: int = 0
    global_reserved: int = 0
    target_pending: int = 0
    pending_deficit: int = 0
    stock_days: float = 0.0
