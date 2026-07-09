"""Matrix and AI-agent persistence models.

These tables are the Phase 1 backend foundation for the planned Agent,
Scheduler, Device Matrix, and Vision layers. Existing collection and sending
flows can keep running while new services begin writing structured state here.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from server.models import Base


def _utcnow():
    return datetime.now(timezone.utc)


class DeviceState(Base):
    __tablename__ = "sa_device_state"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    device_id = Column(
        String(36), ForeignKey("sa_devices.id"), nullable=False, index=True
    )
    job_id = Column(String(36), ForeignKey("sa_jobs.id"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="idle", index=True)
    current_app = Column(String(64), default="")
    current_screen = Column(String(128), default="")
    health = Column(JSON, default=dict)
    consecutive_failures = Column(Integer, default=0)
    cooldown_until = Column(DateTime)
    last_heartbeat = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User")
    device = relationship("Device")
    job = relationship("Job")


class TaskGraph(Base):
    __tablename__ = "sa_task_graphs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    industry_slug = Column(String(64), default="", index=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id"), nullable=True, index=True)
    name = Column(String(128), nullable=False, default="")
    task_type = Column(String(32), nullable=False, default="send", index=True)
    status = Column(String(32), nullable=False, default="draft", index=True)
    priority = Column(Integer, default=100)
    graph = Column(JSON, default=dict)
    retry_policy = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User")
    job = relationship("Job")


class AgentMemory(Base):
    __tablename__ = "sa_agent_memory"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    industry_slug = Column(String(64), default="", index=True)
    device_id = Column(
        String(36), ForeignKey("sa_devices.id"), nullable=True, index=True
    )
    subject_type = Column(String(64), default="", index=True)
    subject_id = Column(String(128), default="", index=True)
    memory_type = Column(String(32), nullable=False, default="observation", index=True)
    content = Column(JSON, default=dict)
    score = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User")
    device = relationship("Device")


class ScreenSnapshot(Base):
    __tablename__ = "sa_screen_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    device_id = Column(
        String(36), ForeignKey("sa_devices.id"), nullable=False, index=True
    )
    job_id = Column(String(36), ForeignKey("sa_jobs.id"), nullable=True, index=True)
    task_id = Column(String(36), nullable=True, index=True)
    stage = Column(String(32), default="")
    screen_name = Column(String(128), default="", index=True)
    blocker = Column(String(64), default="")
    image_path = Column(String(512), default="")
    ocr_text = Column(Text, default="")
    ui_tree = Column(JSON, default=dict)
    confidence = Column(Integer, default=0)
    captured_at = Column(DateTime, default=_utcnow, index=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")
    device = relationship("Device")
    job = relationship("Job")


class ExecutionLog(Base):
    __tablename__ = "sa_execution_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("sa_jobs.id"), nullable=True, index=True)
    device_id = Column(
        String(36), ForeignKey("sa_devices.id"), nullable=True, index=True
    )
    action = Column(String(64), nullable=False, default="", index=True)
    target = Column(String(128), default="")
    status = Column(String(32), nullable=False, default="started", index=True)
    detail = Column(Text, default="")
    latency_ms = Column(Integer, default=0)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow, index=True)

    user = relationship("User")
    job = relationship("Job")
    device = relationship("Device")
