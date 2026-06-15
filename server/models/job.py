"""Background job model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from server.models import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "sa_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    industry_slug = Column(String(64), default="", index=True)
    industry_name = Column(String(128), default="")
    type = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="running", index=True)
    progress = Column(Integer, default=0)
    payload = Column(JSON, default=dict)
    error = Column(String(1000), default="")
    cancel_requested = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    completed_at = Column(DateTime)

    user = relationship("User")
