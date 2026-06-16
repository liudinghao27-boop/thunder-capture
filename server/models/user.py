"""User model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String

from server.models import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "sa_users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
