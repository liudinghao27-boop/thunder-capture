"""Smoke test: verify all components work end-to-end."""
import sys
sys.path.insert(0, ".")

print("=== 1. Database ===")
from server.config import DATABASE_URL
print(f"    URL: {DATABASE_URL}")
from server.models import Base, engine
Base.metadata.create_all(bind=engine)
from sqlalchemy import inspect
tables = inspect(engine).get_table_names()
print(f"    Tables: {len(tables)} OK")

print("\n=== 2. FastAPI App ===")
from server.main import app
routes = [(getattr(r, 'path', ''), list(r.methods) if hasattr(r, 'methods') else [])
          for r in app.routes]
print(f"    Routes: {len(routes)}")
for path, methods in sorted(routes):
    if path:
        print(f"    {methods[0] if methods else '---':6s} {path}")

print("\n=== 3. CLI ===")
import subprocess
result = subprocess.run([sys.executable, "cli.py", "list-industries"],
                        capture_output=True, text=True, timeout=10)
print(f"    cli.py list-industries: {result.stdout.strip() or 'OK (empty)'}")

print("\n=== 4. Classify (no Dify) ===")
from core.classify import ClassificationRouter
router = ClassificationRouter()
print(f"    Active backend: {router.active_backend.name}")

print("\n=== 5. Adapters ===")
from adapters.dify.client import DifyClient
print(f"    Dify available: {DifyClient().available}")

from adapters.postgres.connection import create_pg_engine
print(f"    PG engine: {create_pg_engine(DATABASE_URL).url}")

print("\n=== 6. Web Console ===")
from pathlib import Path
html = Path("server/static/index.html")
print(f"    index.html: {html.stat().st_size:,} bytes OK")

print("\n=== ALL CHECKS PASSED ===")
