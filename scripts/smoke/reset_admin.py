"""Reset admin user password from environment variable.

Usage:
    THUNDER_ADMIN_PASSWORD=your-strong-password python scripts/smoke/reset_admin.py

This script will delete all existing users and create a single admin user
with the provided password. If THUNDER_ADMIN_PASSWORD is not set, it exits
with an error.
"""

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Allow importing from project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.auth import hash_password
from server.config import DATABASE_URL
from server.models.user import User


def main() -> int:
    password = os.getenv("THUNDER_ADMIN_PASSWORD", "").strip()
    if not password:
        print(
            "[ERROR] THUNDER_ADMIN_PASSWORD environment variable is required.",
            file=sys.stderr,
        )
        print(
            "Example: THUNDER_ADMIN_PASSWORD=your-strong-password python scripts/smoke/reset_admin.py",
            file=sys.stderr,
        )
        return 1

    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(User.id).all()
        print(f"Existing users: {len(existing)}")

        db.query(User).delete()

        admin = User(
            username="admin",
            password_hash=hash_password(password),
        )
        db.add(admin)
        db.commit()

        after = db.query(User.username).all()
        print(f"After reset: {[r[0] for r in after]}")
        print("Done. admin password set from THUNDER_ADMIN_PASSWORD.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] Failed to reset admin: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
