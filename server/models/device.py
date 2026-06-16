"""Device model — ADB-connected phones for sending."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from server.models import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Device(Base):
    __tablename__ = "sa_devices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("sa_users.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)             # "oppo-main"
    adb_serial = Column(String(128), nullable=False)
    daily_limit = Column(Integer, default=15)
    min_interval_sec = Column(Integer, default=90)
    is_active = Column(Boolean, default=True)
    last_heartbeat = Column(DateTime, default=_utcnow)

    user = relationship("User")
