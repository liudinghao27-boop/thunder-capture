#!/usr/bin/env python3
"""Check test environment readiness for lead collection manual testing."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Load environment variables from project .env file if present.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=False)
    except Exception:
        pass


def check_database():
    print("=== Database Check ===")
    db_url = os.environ.get("THUNDER_DATABASE_URL", "")
    if not db_url:
        print("WARN: THUNDER_DATABASE_URL not set in environment")
        return False
    parsed = urlparse(db_url)
    print(f"Scheme: {parsed.scheme}")
    print(f"Host: {parsed.hostname}")
    print(f"Port: {parsed.port}")
    print(f"Database: {parsed.path.lstrip('/')}")

    try:
        if parsed.scheme.startswith("postgresql"):
            import psycopg2
            conn = psycopg2.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path.lstrip("/"),
                user=parsed.username,
                password=parsed.password,
            )
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            print(f"OK: PostgreSQL connected - {version}")
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name IN (
                    'sa_jobs', 'sa_task_queue', 'sa_industry_daily_quota', 'sa_industries', 'sa_users'
                )
            """)
            tables = [r[0] for r in cur.fetchall()]
            print(f"OK: Found tables: {tables}")
            cur.close()
            conn.close()
            return True
        elif parsed.scheme.startswith("sqlite"):
            import sqlite3
            db_path = parsed.path or db_url.replace("sqlite:///", "")
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('jobs', 'task_queue', 'industry_daily_quota')")
            tables = [r[0] for r in cur.fetchall()]
            print(f"OK: SQLite connected. Found tables: {tables}")
            conn.close()
            return True
        else:
            print(f"WARN: Unsupported database scheme: {parsed.scheme}")
            return False
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}")
        return False


def check_redis():
    print("\n=== Redis Check ===")
    redis_url = os.environ.get("REDIS_URL", os.environ.get("THUNDER_REDIS_URL", ""))
    if not redis_url:
        print("WARN: REDIS_URL/THUNDER_REDIS_URL not set")
        return False
    try:
        import redis as redis_lib
        r = redis_lib.from_url(redis_url)
        pong = r.ping()
        print(f"OK: Redis ping = {pong}")
        return True
    except Exception as e:
        print(f"ERROR: Redis connection failed: {e}")
        return False


def check_cookies():
    print("\n=== Cookie Check ===")
    cookie_path = Path("data/douyin_cookies.json")
    if not cookie_path.exists():
        print("ERROR: data/douyin_cookies.json not found")
        return False
    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        print(f"OK: Cookie file loaded, {len(cookies)} entries")
        now = datetime.now(timezone.utc).timestamp()
        key_fields = ["sessionid", "uid_tt", "sid_guard"]
        for field in key_fields:
            matches = [c for c in cookies if c.get("name") == field and c.get("value") and c.get("expires", -1) > now]
            if not matches:
                print(f"WARN: Valid {field} not found or expired")
                return False
            else:
                print(f"OK: {field} valid")
        return True
    except Exception as e:
        print(f"ERROR: Cookie file invalid: {e}")
        return False


def check_industry_configs():
    print("\n=== Industry Config Check ===")
    config_dir = Path("config/industries")
    if not config_dir.exists():
        print("WARN: config/industries not found")
        return False
    files = list(config_dir.glob("*.yaml"))
    print(f"OK: Found {len(files)} industry config files: {[f.name for f in files]}")
    return True


def check_browser():
    print("\n=== Browser Check ===")
    from core.browser_orchestrator import find_chrome_path
    path = find_chrome_path()
    if path:
        print(f"OK: Chrome/Edge found at {path}")
        return True
    else:
        print("ERROR: Chrome/Edge not found. ShadowBrowser may fail.")
        return False


def main():
    results = {
        "database": check_database(),
        "redis": check_redis(),
        "cookies": check_cookies(),
        "industry_configs": check_industry_configs(),
        "browser": check_browser(),
    }
    print("\n=== Summary ===")
    for key, ok in results.items():
        print(f"{key}: {'OK' if ok else 'FAIL'}")
    if all(results.values()):
        print("\nEnvironment ready for manual testing.")
    else:
        print("\nEnvironment NOT ready. Please fix failures before testing.")


if __name__ == "__main__":
    main()
