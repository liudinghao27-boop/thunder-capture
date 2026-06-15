"""PostgreSQL adapter.

Replaces SQLite for production deployments. Key changes:

1. DATABASE_URL in .env changes from:
     sqlite:///data/thunder.db
   to:
     postgresql+psycopg2://user:pass@host:5432/thunder

2. Alembic manages migrations under adapters/postgres/migrations/

3. SQLAlchemy models use PostgreSQL-native types (UUID, JSONB, ARRAY)
   and skip_locked=True actually works for task claiming.

Migration path:
   pip install -r requirements/adapters.txt
   alembic init adapters/postgres/migrations
   alembic revision --autogenerate -m "init"
   alembic upgrade head
"""
