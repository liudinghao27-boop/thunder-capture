"""SQLAlchemy model registry and session helpers."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from server.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Import all models so SQLAlchemy can resolve cross-file relationships.
from server.models.user import User  # noqa: E402, F401
from server.models.industry import Industry  # noqa: E402, F401
from server.models.device import Device  # noqa: E402, F401
from server.models.job import Job  # noqa: E402, F401
from server.models.matrix import (  # noqa: E402, F401
    AgentMemory,
    DeviceState,
    ExecutionLog,
    ScreenSnapshot,
    TaskGraph,
)
from server.models.task import (  # noqa: E402, F401
    TargetBlogger,
    CollectedVideo,
    TaskQueue,
    ActionLog,
    ConsumerState,
    CollectorState,
    IndustryDailyQuota,
)


def get_db():
    """FastAPI dependency: yield a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
