"""User model."""

import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String

from server.models import Base

logger = logging.getLogger("thunder.models.user")


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "sa_users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    deepseek_key = Column(String(128), default="")
    zhipu_key = Column(String(128), default="")
    openai_key = Column(String(128), default="")


def create_default_admin() -> None:
    """Create a default admin user if no users exist.

    The password is read from the THUNDER_ADMIN_PASSWORD environment variable.
    If not set, a random password is generated without printing the secret.
    """
    from server.auth import hash_password
    from server.models import SessionLocal

    db = SessionLocal()
    try:
        has_users = db.query(User.id).first() is not None
        if has_users:
            logger.info("Users already exist; skipping default admin creation.")
            return

        password = os.getenv("THUNDER_ADMIN_PASSWORD", "").strip()
        if not password:
            password = uuid.uuid4().hex[:16]
            logger.warning(
                "THUNDER_ADMIN_PASSWORD not set. Generated a random default admin password. "
                "Set THUNDER_ADMIN_PASSWORD and recreate the admin user if you need password login."
            )

        admin = User(
            username="admin",
            password_hash=hash_password(password),
        )
        db.add(admin)
        db.commit()
        print("Default admin user created.")
    except Exception as exc:  # pragma: no cover - best effort
        db.rollback()
        logger.warning("Failed to create default admin: %s", exc)
        raise
    finally:
        db.close()
