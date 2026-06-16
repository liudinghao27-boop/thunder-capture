import asyncio
import json
import logging
from pathlib import Path

from core.config import IndustryConfig
from core.browser_orchestrator import ShadowBrowser

log = logging.getLogger("thunder.discover")
BASE_DIR = Path(__file__).resolve().parent.parent
MC_DIR = BASE_DIR / "deps" / "MediaCrawler"

async def run_discovery(industry: IndustryConfig, max_authors=None, video_age_days=7,
                       skip_discover=False, crawldir: str = None,
                       should_stop=None):
    
    # 1. Update MediaCrawler config
    base_cfg_path = MC_DIR / "config" / "base_config.py"
    if not base_cfg_path.exists():
        log.error(f"MediaCrawler not found at {MC_DIR}. Did you clone it?")
        return []

    with open(base_cfg_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Set config values
    import re
    content = re.sub(r'SAVE_DATA_OPTION\s*=\s*".*?"', 'SAVE_DATA_OPTION = "jsonl"', content)
    content = re.sub(r'ENABLE_GET_COMMENTS\s*=\s*(True|False)', 'ENABLE_GET_COMMENTS = True', content)
    content = re.sub(r'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES\s*=\s*\d+', 'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 50', content)
    
    # Enable CDP mode dynamically
    content = re.sub(r'ENABLE_CDP_MODE\s*=\s*(True|False)', 'ENABLE_CDP_MODE = True', content)
    
    with open(base_cfg_path, "w", encoding="utf-8") as f:
        f.write(content)

    shadow_browser = ShadowBrowser(user_data_dir=str(BASE_DIR / "data" / "chrome_data"))
    try:
        shadow_browser.start()
        
        # Inject dynamic CDP port into base_config
        with open(base_cfg_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r'CDP_DEBUG_PORT\s*=\s*\d+', f'CDP_DEBUG_PORT = {shadow_browser.port}', content)
        with open(base_cfg_path, "w", encoding="utf-8") as f:
            f.write(content)


        platforms_map = {"douyin": "dy", "xiaohongshu": "xhs"}
        configured_platforms = [str(p).strip() for p in (getattr(industry, "platforms", None) or ["douyin"]) if str(p).strip()]
        
        all_comments = []
    
        for p in configured_platforms:
            mc_platform = platforms_map.get(p, "dy")
            log.info(f"Starting MediaCrawler for {p} ({mc_platform})...")
            
            keywords = industry.keywords
            if not keywords:
                continue
                
            if isinstance(keywords, list):
                keywords_str = ",".join(keywords)
            else:
                keywords_str = str(keywords)
                
            cmd = [
                "python", "main.py", 
                "--platform", mc_platform,
                "--type", "search",
                "--keywords", keywords_str
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(MC_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            # Log the output regardless of return code
            out_str = stdout.decode('utf-8', errors='ignore')
            err_str = stderr.decode('utf-8', errors='ignore')
            if out_str:
                log.info(f"MediaCrawler stdout: {out_str}")
            if err_str:
                log.info(f"MediaCrawler stderr: {err_str}")
                
            if process.returncode != 0:
                log.error(f"MediaCrawler failed for {p}: {stderr.decode('utf-8', errors='ignore')}")
                raise RuntimeError(f"MediaCrawler {p} error")

            log.info(f"MediaCrawler finished for {p}. Parsing results...")

            # Parse JSONL results
            # MediaCrawler saves douyin data to data/douyin/jsonl, but we pass --platform dy
            # So we map mc_platform back to the folder name used by MediaCrawler
            folder_name = "douyin" if mc_platform == "dy" else mc_platform
            if mc_platform == "xhs":
                folder_name = "xhs"
                
            data_dir = MC_DIR / "data" / folder_name / "jsonl"
            if not data_dir.exists():
                log.warning(f"No jsonl directory found at {data_dir}")
                continue

            raw_comments = []
            for file in data_dir.glob("*_comments_*.jsonl"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            c = json.loads(line)
                            text = c.get("content") or c.get("text", "")
                            if not text:
                                continue
                                
                            video_id = c.get("aweme_id") or c.get("note_id", "")
                            sec_uid = c.get("sec_uid") or c.get("user_id", "")
                            
                            raw_comments.append({
                                "text": text,
                                "source_name": c.get("nickname", "user"),
                                "source_sec_uid": sec_uid,
                                "source_short_id": c.get("short_id") or "",
                                "source_video_id": video_id,
                                "source_keyword": keywords_str,
                                "industry_slug": industry.slug
                            })
                except Exception as e:
                    log.error(f"Failed to read file {file}: {e}")

            if raw_comments:
                log.info(f"Deduplicating {len(raw_comments)} comments from {p}...")
                # Dedup slightly
                seen = set()
                unique_comments = []
                for c in raw_comments:
                    hash_key = c["source_sec_uid"] + c["text"]
                    if hash_key not in seen:
                        seen.add(hash_key)
                        unique_comments.append(c)

                all_comments.extend(unique_comments)
                log.info(f"Collected {len(unique_comments)} unique comments for {p}.")

            # Clean up the jsonl files so they don't get processed again
            for file in data_dir.glob("*.jsonl"):
                file.unlink(missing_ok=True)
                    
    finally:
        shadow_browser.close()

    return all_comments
