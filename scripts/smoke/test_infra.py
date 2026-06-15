"""Quick smoketest: PostgreSQL + Redis connectivity."""
import sys
sys.path.insert(0, ".")

# 1. PostgreSQL
try:
    from sqlalchemy import create_engine, text
    e = create_engine(
        "postgresql+psycopg2://thunder:thunder123@localhost:5432/thunder",
        connect_args={"connect_timeout": 5}
    )
    with e.connect() as c:
        r = c.execute(text("SELECT 1"))
        print(f"[OK] PostgreSQL: {r.fetchone()}")
        r = c.execute(text("SELECT version()"))
        print(f"     {r.fetchone()[0][:60]}")
    e.dispose()
except Exception as ex:
    print(f"[FAIL] PostgreSQL: {ex}")

# 2. Redis
try:
    import redis
    r = redis.Redis.from_url("redis://localhost:6379/0", socket_connect_timeout=5)
    print(f"[OK] Redis: PING -> {r.ping()}")
except Exception as ex:
    print(f"[FAIL] Redis: {ex}")

# 3. Docker status
import subprocess
try:
    result = subprocess.run(["docker", "compose", "ps"], capture_output=True, text=True, cwd=".")
    print(f"\n[OK] Docker containers:\n{result.stdout}")
except Exception as ex:
    print(f"[FAIL] Docker: {ex}")
