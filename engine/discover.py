"""兼容 shim — 多平台采集调度。新代码请用 engine.collectors."""

import logging
from engine.collectors import get_collector

log = logging.getLogger("thunder.discover")


async def run_discovery(industry, max_authors=12, video_age_days=7,
                       skip_discover=False):
    """迭代行业配置的所有平台，每个平台独立采集，合并返回评论列表。"""
    from engine.queue import init as init_db, queue_stats, blogger_stats

    init_db()
    platforms = industry.platforms

    mode = "增量采集" if skip_discover else "全量采集"
    log.info(f"=== {industry.name} {mode} ===")
    log.info(f"平台: {platforms} | 关键词: {industry.keywords}")

    all_comments = []
    for platform in platforms:
        try:
            cls = get_collector(platform)
            log.info(f"[{platform}] 启动采集器...")
            collector = cls()
            comments = await collector.run(
                industry,
                max_authors=max_authors,
                content_age_days=video_age_days,
                skip_discover=skip_discover,
            )
            all_comments.extend(comments)
            log.info(f"[{platform}] {len(comments)} 条候选评论")
        except Exception as e:
            log.error(f"[{platform}] 采集异常: {e}", exc_info=True)
            continue

    return all_comments
