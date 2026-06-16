"""任务队列 — SQLite WAL 模式，多 consumer 并发安全"""

import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import load_system

_sys = load_system()
DB_PATH = Path(_sys["database"]["path"])
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init():
    db = _conn()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS target_bloggers (
            sec_uid TEXT PRIMARY KEY,
            nickname TEXT NOT NULL,
            uid TEXT DEFAULT '',
            industry_slug TEXT DEFAULT '',
            source_keyword TEXT DEFAULT '',
            source_video_id TEXT DEFAULT '',
            discovered_at TEXT DEFAULT '',
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS collected_videos (
            aweme_id TEXT NOT NULL,
            source_sec_uid TEXT NOT NULL,
            comment_count INTEGER DEFAULT 0,
            collected_at TEXT DEFAULT '',
            PRIMARY KEY (aweme_id, source_sec_uid)
        );
        CREATE TABLE IF NOT EXISTS task_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            industry_slug TEXT DEFAULT '',
            platform TEXT DEFAULT 'douyin',
            keyword TEXT DEFAULT '',
            video_id TEXT NOT NULL,
            video_url TEXT DEFAULT '',
            comment_id TEXT NOT NULL,
            text TEXT NOT NULL,
            user_name TEXT DEFAULT '',
            user_id TEXT DEFAULT '',
            matched_categories TEXT DEFAULT '[]',
            fetched_at TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            consumer_id TEXT,
            claim_token TEXT,
            claimed_at TEXT,
            processed_at TEXT,
            ai_reply TEXT,
            error TEXT,
            UNIQUE(comment_id, video_id)
        );
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            consumer_id TEXT,
            task_id INTEGER,
            target_user TEXT,
            comment_text TEXT,
            ai_reply TEXT,
            status TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS consumer_state (
            consumer_id TEXT PRIMARY KEY,
            daily_sent INTEGER DEFAULT 0,
            last_sent_date TEXT,
            daily_limit INTEGER DEFAULT 15,
            min_interval_sec INTEGER DEFAULT 90,
            total_sent INTEGER DEFAULT 0,
            total_failed INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status);
        CREATE INDEX IF NOT EXISTS idx_task_claimed ON task_queue(consumer_id, status);
        CREATE INDEX IF NOT EXISTS idx_action_ts ON action_log(ts);
    """)
    try:
        db.execute("ALTER TABLE task_queue ADD COLUMN short_id TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE task_queue ADD COLUMN douyin_id TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE task_queue ADD COLUMN unique_id TEXT DEFAULT ''")
    except Exception:
        pass
    db.commit()
    db.close()


# ============================================================
# Blogger CRUD
# ============================================================

def add_blogger(sec_uid: str, nickname: str, uid: str = "",
                industry_slug: str = "", source_keyword: str = "",
                source_video_id: str = "") -> bool:
    db = _conn()
    try:
        db.execute(
            "INSERT OR IGNORE INTO target_bloggers "
            "(sec_uid, nickname, uid, industry_slug, source_keyword, source_video_id, discovered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sec_uid, nickname, uid, industry_slug, source_keyword,
             source_video_id, datetime.now().isoformat()),
        )
        db.commit()
        ok = db.total_changes > 0
        db.close()
        return ok
    except Exception:
        db.close()
        return False


def get_bloggers(status: str = "active", industry_slug: str = "") -> list[dict]:
    db = _conn()
    if status == "all":
        if industry_slug:
            cur = db.execute(
                "SELECT * FROM target_bloggers WHERE industry_slug=? "
                "ORDER BY discovered_at DESC", (industry_slug,),
            )
        else:
            cur = db.execute("SELECT * FROM target_bloggers ORDER BY discovered_at DESC")
    elif industry_slug:
        cur = db.execute(
            "SELECT * FROM target_bloggers WHERE status=? AND industry_slug=? "
            "ORDER BY discovered_at DESC",
            (status, industry_slug),
        )
    else:
        cur = db.execute(
            "SELECT * FROM target_bloggers WHERE status=? ORDER BY discovered_at DESC",
            (status,),
        )
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    db.close()
    return [dict(zip(cols, r)) for r in rows]


def set_blogger_status(sec_uid: str, status: str) -> bool:
    db = _conn()
    db.execute("UPDATE target_bloggers SET status=? WHERE sec_uid=?", (status, sec_uid))
    db.commit()
    ok = db.total_changes > 0
    db.close()
    return ok


def blogger_stats(industry_slug: str = "") -> dict:
    db = _conn()
    if industry_slug:
        cur = db.execute(
            "SELECT status, COUNT(*) FROM target_bloggers WHERE industry_slug=? "
            "GROUP BY status", (industry_slug,))
    else:
        cur = db.execute(
            "SELECT status, COUNT(*) FROM target_bloggers GROUP BY status")
    stats = dict(cur.fetchall())
    db.close()
    return {"total": sum(stats.values()), "active": stats.get("active", 0),
            "paused": stats.get("paused", 0), "ignored": stats.get("ignored", 0)}


def is_video_collected(aweme_id: str, sec_uid: str) -> bool:
    db = _conn()
    row = db.execute(
        "SELECT 1 FROM collected_videos WHERE aweme_id=? AND source_sec_uid=?",
        (aweme_id, sec_uid),
    ).fetchone()
    db.close()
    return row is not None


def mark_video_collected(aweme_id: str, sec_uid: str, comment_count: int = 0) -> bool:
    db = _conn()
    try:
        db.execute(
            "INSERT OR IGNORE INTO collected_videos "
            "(aweme_id, source_sec_uid, comment_count, collected_at) "
            "VALUES (?, ?, ?, ?)",
            (aweme_id, sec_uid, comment_count, datetime.now().isoformat()),
        )
        db.commit()
        db.close()
        return True
    except Exception:
        db.close()
        return False


# ============================================================
# Task operations
# ============================================================

def enqueue_task(comment: dict) -> bool:
    db = _conn()
    # Dedup: skip if this user already has a pending/claimed task
    user_id = comment.get("sec_uid") or comment.get("user_id", "")
    if user_id:
        existing = db.execute(
            "SELECT 1 FROM task_queue WHERE user_id=? AND status IN ('pending','claimed','done') LIMIT 1",
            (user_id,),
        ).fetchone()
        if existing:
            db.close()
            return False
    text = comment.get("content") or comment.get("text", "")
    try:
        db.execute(
            "INSERT OR IGNORE INTO task_queue "
            "(industry_slug, platform, keyword, video_id, video_url, comment_id, "
            "text, user_name, user_id, short_id, douyin_id, unique_id, matched_categories, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (comment.get("industry_slug", ""), comment.get("platform", "douyin"),
             comment.get("keyword", ""),
             comment.get("aweme_id") or comment.get("video_id", "") or comment.get("post_id", ""),
             comment.get("video_url", "") or comment.get("post_url", ""), comment.get("comment_id", ""),
             text,
             comment.get("nickname") or comment.get("user_name", ""),
             comment.get("sec_uid") or comment.get("user_id", ""),
             comment.get("short_id", ""),
             comment.get("douyin_id", ""),
             comment.get("unique_id", ""),
             str(comment.get("matched_categories", [])),
             comment.get("fetched_at", datetime.now().isoformat())),
        )
        db.commit()
        ok = db.total_changes > 0
        db.close()
        return ok
    except Exception:
        db.close()
        return False


def claim_task(consumer_id: str) -> dict | None:
    db = _conn()
    token = str(uuid.uuid4())
    now = datetime.now().isoformat()
    now_ts = int(datetime.now().timestamp())
    try:
        db.execute("BEGIN IMMEDIATE")
        cur = db.execute(
            "SELECT *, "
            "CASE "
            "  WHEN ? - CAST(strftime('%s', fetched_at) AS INTEGER) < 86400 THEN 1 "
            "  WHEN ? - CAST(strftime('%s', fetched_at) AS INTEGER) < 172800 THEN 2 "
            "  ELSE 3 "
            "END AS priority "
            "FROM task_queue "
            "WHERE status='pending' AND user_name != '' "
            "ORDER BY priority ASC, fetched_at ASC LIMIT 1",
            (now_ts, now_ts),
        )
        row = cur.fetchone()
        if not row:
            db.commit()
            db.close()
            return None
        cols = [d[0] for d in cur.description]
        task = dict(zip(cols, row))
        task_id = task["id"]
        cur = db.execute(
            "UPDATE task_queue SET status=?, consumer_id=?, claim_token=?, claimed_at=? "
            "WHERE id=? AND status=?",
            ("claimed", consumer_id, token, now, task_id, "pending"),
        )
        if cur.rowcount == 0:
            db.commit()
            db.close()
            return None
        db.commit()
        db.close()
        task["status"] = "claimed"
        task["consumer_id"] = consumer_id
        return task
    except Exception:
        db.close()
        return None


def mark_task_done(task_id: int, consumer_id: str, ai_reply: str = ""):
    db = _conn()
    db.execute(
        "UPDATE task_queue SET status='done', processed_at=?, ai_reply=? WHERE id=?",
        (datetime.now().isoformat(), ai_reply, task_id),
    )
    db.commit()
    db.close()


def mark_task_failed(task_id: int, consumer_id: str, error: str = ""):
    db = _conn()
    db.execute(
        "UPDATE task_queue SET status='failed', processed_at=?, error=? WHERE id=?",
        (datetime.now().isoformat(), error[:500], task_id),
    )
    db.commit()
    db.close()


def mark_task_retry(task_id: int, consumer_id: str, error: str = ""):
    """Mark task for retry — reset to pending for another device later."""
    db = _conn()
    db.execute(
        "UPDATE task_queue SET status='pending', consumer_id=NULL, "
        "claim_token=NULL, claimed_at=NULL, error=? WHERE id=?",
        (error[:200], task_id),
    )
    db.commit()
    db.close()


def reclaim_stale_claims(timeout_minutes: int = 30) -> int:
    db = _conn()
    cutoff = (datetime.now() - timedelta(minutes=timeout_minutes)).isoformat()
    cur = db.execute(
        "UPDATE task_queue SET status='pending', consumer_id=NULL, "
        "claim_token=NULL, claimed_at=NULL "
        "WHERE status='claimed' AND claimed_at < ?",
        (cutoff,),
    )
    n = cur.rowcount
    db.commit()
    db.close()
    return n


def log_action(consumer_id: str, task_id: int, target_user: str,
               comment_text: str, ai_reply: str, status: str, error: str = ""):
    db = _conn()
    db.execute(
        "INSERT INTO action_log (ts, consumer_id, task_id, target_user, "
        "comment_text, ai_reply, status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), consumer_id, task_id,
         target_user, comment_text, ai_reply, status, error),
    )
    db.commit()
    db.close()


# ============================================================
# Consumer state
# ============================================================

def get_consumer_state(consumer_id: str) -> dict:
    db = _conn()
    db.execute("INSERT OR IGNORE INTO consumer_state (consumer_id) VALUES (?)",
               (consumer_id,))
    db.commit()
    row = db.execute(
        "SELECT * FROM consumer_state WHERE consumer_id=?", (consumer_id,)
    ).fetchone()
    db.close()
    cols = ["consumer_id", "daily_sent", "last_sent_date",
            "daily_limit", "min_interval_sec", "total_sent", "total_failed"]
    state = dict(zip(cols, row))
    today = str(date.today())
    if state["last_sent_date"] != today:
        state["daily_sent"] = 0
    return state


def increment_consumer_sent(consumer_id: str):
    db = _conn()
    today = str(date.today())
    db.execute(
        "UPDATE consumer_state "
        "SET daily_sent = CASE WHEN last_sent_date=? THEN daily_sent+1 ELSE 1 END, "
        "last_sent_date = ?, total_sent = total_sent + 1 "
        "WHERE consumer_id=?",
        (today, today, consumer_id),
    )
    db.commit()
    db.close()


def increment_consumer_failed(consumer_id: str):
    db = _conn()
    db.execute(
        "UPDATE consumer_state SET total_failed = total_failed + 1 WHERE consumer_id=?",
        (consumer_id,),
    )
    db.commit()
    db.close()


def queue_stats(industry_slug: str = "") -> dict:
    db = _conn()
    if industry_slug:
        cur = db.execute(
            "SELECT status, COUNT(*) FROM task_queue WHERE industry_slug=? "
            "GROUP BY status", (industry_slug,))
    else:
        cur = db.execute("SELECT status, COUNT(*) FROM task_queue GROUP BY status")
    stats = dict(cur.fetchall())
    db.close()
    return {"total": sum(stats.values()), "pending": stats.get("pending", 0),
            "claimed": stats.get("claimed", 0), "done": stats.get("done", 0),
            "failed": stats.get("failed", 0)}


def consumer_stats() -> list[dict]:
    db = _conn()
    cur = db.execute("SELECT * FROM consumer_state ORDER BY consumer_id")
    rows = cur.fetchall()
    db.close()
    cols = ["consumer_id", "daily_sent", "last_sent_date",
            "daily_limit", "min_interval_sec", "total_sent", "total_failed"]
    return [dict(zip(cols, r)) for r in rows]
