"""PostgreSQL adapter.

Replaces SQLite for production deployments. Key changes:

1. DATABASE_URL in .env changes from:
     sqlite:///data/thunder.db
   to:
     postgresql+psycopg2://user:pass@host:5432/thunder

2. Alembic manages migrations under adapters/postgres/migrations/

3. SQLAlchemy models use PostgreSQL-native types (UUID, JSONB, ARRAY)
   and skip_locked=True actually works for task claiming.

Migration commands (from project root):
   # Generate a new migration after model changes
   alembic revision --autogenerate -m "describe change"

   # Apply migrations
   alembic upgrade head

   # Rollback one revision
   alembic downgrade -1

Development note: env.py reads THUNDER_DATABASE_URL from server.config, so
migrations work against SQLite as well as PostgreSQL.
"""
