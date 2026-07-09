"""Industry model — configurable campaign settings."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from server.models import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Industry(Base):
    __tablename__ = "sa_industries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)  # "征兵咨询"
    slug = Column(String(64), nullable=False)  # "recruitment"
    keywords = Column(JSON, default=list)  # ["征兵","当兵"...]
    platforms = Column(JSON, default=lambda: ["douyin"])
    reply_tone = Column(String(64), default="业内人士")  # "退伍老兵"
    reply_style = Column(String(256), default="亲切专业")
    reply_hook = Column(String(256), default="")
    categories = Column(JSON, default=list)  # ["入伍条件"..]
    daily_limit = Column(Integer, default=15)
    video_max_age_days = Column(Integer, default=14)
    comment_max_age_hours = Column(Integer, default=48)
    llm_provider = Column(String(32), default="deepseek")
    llm_model = Column(String(64), default="deepseek-v4-flash")
    intent_keywords = Column(JSON, default=list)
    noise_keywords = Column(JSON, default=list)
    target_users = Column(JSON, default=list)
    matrix_target_devices = Column(Integer, default=30)
    lead_inventory_days = Column(Integer, default=3)
    global_daily_limit = Column(Integer, default=0)
    auto_replenish_enabled = Column(Boolean, default=False)
    replenish_threshold_days = Column(Integer, default=1)
    keyword_batch_size = Column(Integer, default=12)
    collect_authors_per_run = Column(Integer, default=60)
    collect_video_limit = Column(Integer, default=120)
    compliance_mode = Column(Boolean, default=False)
    webhook_url = Column(String(512), default="")
    auto_export_enabled = Column(Boolean, default=False)
    send_start_time = Column(String(8), default="09:00")
    send_end_time = Column(String(8), default="13:00")
    pause_weekends = Column(Boolean, default=False)
    daily_send_max = Column(Integer, default=0)
    hourly_send_limit = Column(Integer, default=0)
    effect_webhook_url = Column(String(512), default="")
    reply_variants = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uix_industry_user_slug"),
    )
