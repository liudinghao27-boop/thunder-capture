"""SQLAlchemy models for matrix tasks and collector state."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, UniqueConstraint
from datetime import datetime, timezone
from server.models import Base

def _utcnow():
    return datetime.now(timezone.utc)

class TargetBlogger(Base):
    __tablename__ = "sa_target_bloggers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_slug = Column(String(64), index=True, nullable=False)
    sec_uid = Column(String(128), index=True, nullable=False)
    nickname = Column(String(128), default="")
    uid = Column(String(128), default="")
    source_keyword = Column(String(128), default="")
    source_video_id = Column(String(128), default="")
    discovered_at = Column(String(64), default="")
    status = Column(String(32), default="active", index=True)

    __table_args__ = (
        UniqueConstraint("industry_slug", "sec_uid", name="uix_industry_sec_uid"),
    )


class CollectedVideo(Base):
    __tablename__ = "sa_collected_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    aweme_id = Column(String(128), index=True, nullable=False)
    source_sec_uid = Column(String(128), index=True, nullable=False)
    comment_count = Column(Integer, default=0)
    collected_at = Column(String(64), default="")

    __table_args__ = (
        UniqueConstraint("aweme_id", "source_sec_uid", name="uix_aweme_source"),
    )


class TaskQueue(Base):
    __tablename__ = "sa_task_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_slug = Column(String(64), index=True, default="")
    platform = Column(String(32), default="douyin")
    keyword = Column(String(128), default="")
    video_id = Column(String(128), index=True, nullable=False)
    video_url = Column(String(256), default="")
    comment_id = Column(String(128), index=True, nullable=False)
    text = Column(Text, default="")
    user_name = Column(String(128), default="")
    user_id = Column(String(128), default="")
    matched_categories = Column(String(512), default="[]")
    fetched_at = Column(String(64), default="")
    status = Column(String(32), default="pending", index=True)
    consumer_id = Column(String(128), index=True)
    claim_token = Column(String(128))
    claimed_at = Column(String(64))
    processed_at = Column(String(64))
    ai_reply = Column(Text, default="")
    error = Column(Text, default="")
    
    # Douyin specific identifiers
    short_id = Column(String(128), default="")
    douyin_id = Column(String(128), default="")
    unique_id = Column(String(128), default="")
    
    # Retry & backoff
    retry_count = Column(Integer, default=0)
    retry_after = Column(String(64), default="")
    
    # Source attribution
    source_keyword = Column(String(128), default="")
    source_creator = Column(String(128), default="")
    source_video_desc = Column(Text, default="")
    
    # Job/Ownership context
    owner_user_id = Column(String(64), index=True, default="")
    job_id = Column(String(64), index=True, default="")

    __table_args__ = (
        UniqueConstraint("comment_id", "video_id", name="uix_comment_video"),
    )


class ActionLog(Base):
    __tablename__ = "sa_action_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(String(64), index=True)
    consumer_id = Column(String(128), index=True)
    task_id = Column(Integer)
    target_user = Column(String(128))
    comment_text = Column(Text)
    ai_reply = Column(Text)
    status = Column(String(32), index=True)
    error = Column(Text)


class ConsumerState(Base):
    __tablename__ = "sa_consumer_state"

    consumer_id = Column(String(128), primary_key=True)
    daily_sent = Column(Integer, default=0)
    last_sent_date = Column(String(32))
    daily_limit = Column(Integer, default=15)
    min_interval_sec = Column(Integer, default=90)
    total_sent = Column(Integer, default=0)
    total_failed = Column(Integer, default=0)
    
    # Wave limit
    wave_sent = Column(Integer, default=0)
    waves_today = Column(Integer, default=0)
    rate_limited_at = Column(String(64), default="")
    adaptive_limit = Column(Integer, default=8)
    last_wave_date = Column(String(32), default="")
    nurture_done_today = Column(Integer, default=0)


class CollectorState(Base):
    __tablename__ = "sa_collector_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_slug = Column(String(64), index=True, nullable=False)
    platform = Column(String(32), nullable=False)
    key = Column(String(128), nullable=False)
    value = Column(Text, default="")
    updated_at = Column(String(64), default="")

    __table_args__ = (
        UniqueConstraint("industry_slug", "platform", "key", name="uix_collector_state"),
    )


class IndustryDailyQuota(Base):
    __tablename__ = "sa_industry_daily_quota"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_slug = Column(String(64), index=True, nullable=False)
    day = Column(String(32), index=True, nullable=False)
    sent = Column(Integer, default=0)
    reserved = Column(Integer, default=0)
    updated_at = Column(String(64), default="")

    __table_args__ = (
        UniqueConstraint("industry_slug", "day", name="uix_industry_day_quota"),
    )
