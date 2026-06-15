"""End-to-end pipeline test: classify -> enqueue -> verify."""
import sys
sys.path.insert(0, ".")

from core.config import load_industry
from core.classify import classify_batch, enqueue_classified
from server.services.task_stats import queue_stats

ind = load_industry("recruitment")
comments = [
    {"text": "请问征兵需要什么条件", "nickname": "A", "keyword": "征兵",
     "source_video_desc": "", "source_sec_uid": "test001", "source_short_id": "s1",
     "source_video_id": "v1", "source_keyword": "征兵", "industry_slug": "recruitment"},
    {"text": "我儿子想当兵，体检有什么要求", "nickname": "B", "keyword": "当兵",
     "source_video_desc": "", "source_sec_uid": "test002", "source_short_id": "s2",
     "source_video_id": "v2", "source_keyword": "当兵", "industry_slug": "recruitment"},
]

print(f"1. Classifying {len(comments)} comments...")
results = classify_batch(comments, ind)
print(f"   Passed: {len(results)}")

print("2. Enqueuing...")
count = enqueue_classified(results)
print(f"   Enqueued: {count}")

print("3. Checking queue...")
stats = queue_stats("recruitment")
print(f"   Pending: {stats['pending']}, Done: {stats['done']}, Failed: {stats['failed']}")

if stats['pending'] > 0:
    print("\n>>> PIPELINE WORKS: classify -> enqueue -> queue ready <<<")
else:
    print("\n>>> ISSUE: nothing in queue <<<")
