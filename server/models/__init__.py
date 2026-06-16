"""SQLAlchemy models."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from server.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Import all models so SQLAlchemy can resolve cross-file relationships
from server.models.user import User  # noqa: E402, F401
from server.models.industry import Industry  # noqa: E402, F401
from server.models.device import Device  # noqa: E402, F401


def get_db():
    """FastAPI dependency: yield a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

