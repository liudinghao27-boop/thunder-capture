"""Test: parse collected JSONL → classify → enqueue → verify."""
import sys, json, logging
sys.path.insert(0, ".")
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("test")

BASE_DIR = Path(".").resolve()
MC_DIR = BASE_DIR / "deps" / "MediaCrawler"

# 1. Parse collected data
data_dir = MC_DIR / "data" / "douyin" / "jsonl"
raw_comments = []
for file in data_dir.glob("*_comments_*.jsonl"):
    log.info(f"Parsing {file.name}...")
    with open(file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            text = c.get("content") or c.get("text", "")
            if not text:
                continue
            raw_comments.append({
                "text": text,
                "source_name": c.get("nickname", "user"),
                "source_sec_uid": c.get("sec_uid") or c.get("user_id", ""),
                "source_short_id": c.get("short_id") or "",
                "source_video_id": c.get("aweme_id") or c.get("note_id", ""),
                "source_keyword": "征兵条件",
                "industry_slug": "recruitment",
            })

log.info(f"Parsed {len(raw_comments)} comments")

# 2. Dedup
seen = set()
unique = []
for c in raw_comments:
    key = c["source_sec_uid"] + c["text"]
    if key not in seen:
        seen.add(key)
        unique.append(c)
log.info(f"After dedup: {len(unique)} unique")

# 3. Classify
from core.config import load_industry
from core.classify import classify_batch, enqueue_classified

ind = load_industry("recruitment")
log.info("Classifying...")
passed = classify_batch(unique[:30], ind)  # Limit to 30 for quick test
log.info(f"Passed: {len(passed)} / 30")

# 4. Enqueue
count = enqueue_classified(passed)
log.info(f"Enqueued: {count}")

# 5. Verify
from server.services.task_stats import queue_stats
stats = queue_stats("recruitment")
log.info(f"Queue: pending={stats['pending']} done={stats['done']} failed={stats['failed']}")

print(f"\n>>> RESULT: {stats['pending']} tasks ready for sending <<<")
