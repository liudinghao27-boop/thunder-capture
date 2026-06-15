"""Test collection module step by step."""
import sys
sys.path.insert(0, ".")

print("=== 1. Browser check ===")
from core.browser_orchestrator import find_chrome_path, find_free_port
chrome = find_chrome_path()
print(f"   Chrome: {chrome}")
print(f"   Free port: {find_free_port()}")

print("\n=== 2. MediaCrawler path ===")
from pathlib import Path
BASE_DIR = Path(".").resolve()
MC_DIR = BASE_DIR / "deps" / "MediaCrawler"
print(f"   MC_DIR: {MC_DIR}")
print(f"   exists: {MC_DIR.exists()}")
print(f"   main.py: {(MC_DIR / 'main.py').exists()}")
print(f"   config:  {(MC_DIR / 'config' / 'base_config.py').exists()}")

print("\n=== 3. Config update test ===")
import re
cfg_path = MC_DIR / "config" / "base_config.py"
with open(cfg_path, "r", encoding="utf-8") as f:
    original = f.read()

# Test regex patterns work
tests = [
    (r'SAVE_DATA_OPTION\s*=\s*".*?"', 'SAVE_DATA_OPTION = "jsonl"'),
    (r'ENABLE_GET_COMMENTS\s*=\s*(True|False)', 'ENABLE_GET_COMMENTS = True'),
    (r'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES\s*=\s*\d+', 'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 50'),
    (r'ENABLE_CDP_MODE\s*=\s*(True|False)', 'ENABLE_CDP_MODE = True'),
]
all_ok = True
for pattern, replacement in tests:
    match = re.search(pattern, original)
    if match:
        print(f"   OK: {pattern[:50]}... → found: {match.group()[:50]}")
    else:
        print(f"   MISS: {pattern[:50]}... → NOT FOUND in base_config.py!")
        all_ok = False

# Restore original
with open(cfg_path, "w", encoding="utf-8") as f:
    f.write(original)
print(f"   Config restored (unchanged)")

print("\n=== 4. Industry config ===")
from core.config import load_industry
ind = load_industry("recruitment")
print(f"   name: {ind.name}")
print(f"   keywords: {ind.keywords[:5]}...")
print(f"   platforms: {ind.platforms}")
print(f"   daily_limit: {ind.daily_limit}")

print("\n=== 5. JSONL parser test ===")
import json
# Simulate MediaCrawler output format
mock_jsonl = [
    {"content": "征兵条件咨询", "nickname": "用户1", "sec_uid": "uid1",
     "short_id": "s1", "aweme_id": "aw1"},
    {"content": "", "nickname": "用户2", "sec_uid": "uid2"},  # Empty → skip
    {"text": "当兵体检要求", "nickname": "用户3", "user_id": "uid3",
     "short_id": "s3", "note_id": "n3"},  # xhs format
]
for c in mock_jsonl:
    text = c.get("content") or c.get("text", "")
    video_id = c.get("aweme_id") or c.get("note_id", "")
    sec_uid = c.get("sec_uid") or c.get("user_id", "")
    if not text:
        print(f"   SKIP (empty): {c.get('nickname','')}")
    else:
        print(f"   OK: {text[:30]} | sec_uid={sec_uid[:10]} | video={video_id}")

print(f"\n=== RESULT: {'ALL OK' if all_ok else 'NEEDS FIXES'} ===")
