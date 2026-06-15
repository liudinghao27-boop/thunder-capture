"""Live test: DeepSeek classification with real API call."""
import sys
sys.path.insert(0, ".")

from core.config import load_industry
from core.classify import classify_batch, ClassificationRouter

ind = load_industry("recruitment")
comments = [
    {"text": "请问征兵需要什么条件？我今年18岁", "nickname": "用户A", "keyword": "征兵", "source_video_desc": ""},
    {"text": "哈哈哈太帅了", "nickname": "用户B", "keyword": "征兵", "source_video_desc": ""},
    {"text": "我儿子想去当兵，视力要求多少？", "nickname": "用户C", "keyword": "征兵", "source_video_desc": ""},
]

router = ClassificationRouter()
print(f"Backend: {router.active_backend.name}")

results = classify_batch(comments, ind)
print(f"Input: {len(comments)}, Passed: {len(results)}")
for r in results:
    cats = r.get("matched_categories", "{}")
    print(f"  [{cats[:60]}] {r['text'][:40]}")
print("DONE")
