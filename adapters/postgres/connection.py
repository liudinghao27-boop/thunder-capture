"""PostgreSQL connection factory — drop-in replacement for SQLite.

To migrate from SQLite to PostgreSQL:
1. Set DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/thunder
2. The existing SQLAlchemy models (server/models/) work as-is
3. PostgreSQL gives you:
   - Real FOR UPDATE SKIP LOCKED (fixes concurrent task claim)
   - JSONB for matched_categories column
   - Connection pooling via SQLAlchemy QueuePool
"""

from __future__ import annotations

import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

log = logging.getLogger("thunder.postgres")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///data/thunder.db",  # Default: keep SQLite for dev
)


def create_pg_engine(database_url: str = "", echo: bool = False):
    """Create SQLAlchemy engine — PostgreSQL or SQLite depending on URL."""
    url = database_url or DATABASE_URL

    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        pool_kwargs = {}
    else:
        connect_args = {}
        pool_kwargs = {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,
        }

    return create_engine(
        url,
        connect_args=connect_args,
        echo=echo,
        **pool_kwargs,
    )


def create_session_factory(engine):
    """Create thread-safe session factory."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
