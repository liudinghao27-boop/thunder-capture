import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Setup path so we can import server models
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from server.models import SessionLocal
from server.models.task import TaskQueue, TargetBlogger, CollectedVideo

DB_PATH = BASE_DIR / "thunder_engine.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"No local SQLite DB found at {DB_PATH}, nothing to migrate.")
        return

    print(f"Connecting to SQLite: {DB_PATH}")
    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    pg_db = SessionLocal()
    
    print("Migrating task_queue...")
    sqlite_cur.execute("SELECT * FROM task_queue")
    tasks = sqlite_cur.fetchall()
    for row in tasks:
        d = dict(row)
        # Parse datetime strings
        for field in ['fetched_at', 'claimed_at', 'processed_at']:
            if d.get(field):
                try:
                    d[field] = datetime.fromisoformat(d[field]).replace(tzinfo=timezone.utc)
                except:
                    d[field] = None
        # Rename or fix fields if necessary
        d.pop('id', None) # let PG auto increment
        
        # We need to map some old statuses to new if needed
        t = TaskQueue(**d)
        pg_db.add(t)
    
    pg_db.commit()
    print(f"Migrated {len(tasks)} tasks.")

    print("Migrating target_bloggers...")
    sqlite_cur.execute("SELECT * FROM target_bloggers")
    bloggers = sqlite_cur.fetchall()
    for row in bloggers:
        d = dict(row)
        for field in ['created_at', 'updated_at']:
            if d.get(field):
                try:
                    d[field] = datetime.fromisoformat(d[field]).replace(tzinfo=timezone.utc)
                except:
                    d[field] = None
        d.pop('id', None)
        t = TargetBlogger(**d)
        pg_db.add(t)
        
    pg_db.commit()
    print(f"Migrated {len(bloggers)} bloggers.")

    print("Migrating collected_videos...")
    try:
        sqlite_cur.execute("SELECT * FROM collected_videos")
        videos = sqlite_cur.fetchall()
        for row in videos:
            d = dict(row)
            if d.get('collected_at'):
                try:
                    d['collected_at'] = datetime.fromisoformat(d['collected_at']).replace(tzinfo=timezone.utc)
                except:
                    d['collected_at'] = None
            d.pop('id', None)
            t = CollectedVideo(**d)
            pg_db.add(t)
            
        pg_db.commit()
        print(f"Migrated {len(videos)} collected videos.")
    except Exception as e:
        print(f"Skipping collected_videos due to error: {e}")

    sqlite_conn.close()
    pg_db.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
