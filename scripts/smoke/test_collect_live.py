"""Live test: MediaCrawler subprocess for Douyin search."""
import sys, asyncio, json, logging, re
from pathlib import Path

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("test")

BASE_DIR = Path(".").resolve()
MC_DIR = BASE_DIR / "deps" / "MediaCrawler"

async def main():
    # 1. Update config
    cfg = MC_DIR / "config" / "base_config.py"
    with open(cfg, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r'SAVE_DATA_OPTION\s*=\s*".*?"', 'SAVE_DATA_OPTION = "jsonl"', content)
    content = re.sub(r'ENABLE_GET_COMMENTS\s*=\s*(True|False)', 'ENABLE_GET_COMMENTS = True', content)
    content = re.sub(r'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES\s*=\s*\d+',
                     'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 20', content)
    content = re.sub(r'ENABLE_CDP_MODE\s*=\s*(True|False)', 'ENABLE_CDP_MODE = True', content)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("Config updated")

    # 2. Start ShadowBrowser
    from core.browser_orchestrator import ShadowBrowser
    browser = ShadowBrowser(str(BASE_DIR / "data" / "chrome_data"))
    browser.start()
    log.info(f"Browser on port {browser.port}")

    # Inject CDP port
    with open(cfg, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r'CDP_DEBUG_PORT\s*=\s*\d+', f'CDP_DEBUG_PORT = {browser.port}', content)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(content)

    # 3. Run MediaCrawler (small test: 1 keyword, max 3 results)
    log.info("Running MediaCrawler...")
    cmd = [
        "python", "main.py",
        "--platform", "dy",
        "--type", "search",
        "--keywords", "征兵条件",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(MC_DIR),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    log.info(f"Return code: {proc.returncode}")
    if stdout:
        log.info(f"stdout: {stdout.decode('utf-8', errors='ignore')[:500]}")
    if stderr:
        err = stderr.decode('utf-8', errors='ignore')
        if err.strip():
            log.info(f"stderr: {err[:500]}")

    # 4. Parse results
    data_dir = MC_DIR / "data" / "douyin" / "jsonl"
    if data_dir.exists():
        for f in data_dir.glob("*.jsonl"):
            with open(f, "r", encoding="utf-8") as fh:
                lines = [l for l in fh if l.strip()]
            log.info(f"  {f.name}: {len(lines)} lines")
            for line in lines[:3]:
                c = json.loads(line)
                text = c.get("content", "")[:50]
                log.info(f"    -> {text}")

    browser.close()
    log.info("Done")

asyncio.run(main())
