"""Quick smoke test for ShadowBrowser startup."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("THUNDER_MEDIACRAWLER_PROXY_URL", "http://127.0.0.1:7897")

from core.browser_orchestrator import ShadowBrowser

browser = ShadowBrowser(user_data_dir=str(BASE_DIR / "data" / "chrome_data_test"))
try:
    browser.start()
    print(f"SUCCESS: ShadowBrowser ready on port {browser.port}")
except Exception as exc:
    print(f"FAILED: {exc}")
    sys.exit(1)
finally:
    browser.close()
    print("Browser closed.")
