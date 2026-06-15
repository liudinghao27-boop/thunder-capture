#!/usr/bin/env python3
"""雷霆捕获系统 — 通用社媒获客 CLI"""

import sys
import os
import io
from pathlib import Path

# Load .env before anything else
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# MUST be first — fix Windows encoding BEFORE any logging or module imports
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer") and not isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import asyncio
import time
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
# Make vendored deps importable
sys.path.insert(0, str(BASE_DIR / "deps" / "crawl4ai"))

from core.config import (
    IndustryConfig, load_system, load_industry,
    list_industries, create_industry,
)
from server.services.task_stats import (
    queue_stats, blogger_source_stats as blogger_stats, 
    get_wave_state as get_consumer_state, get_bloggers, add_blogger
)
from core.classify import classify_batch, enqueue_classified
from core.task.worker import run_senders

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/thunder.log", encoding="utf-8")
    ],
)
log = logging.getLogger("thunder")


def cmd_create(args):
    """新建行业"""
    keywords = [k.strip() for k in args.keywords.split(",")]
    path = create_industry(
        slug=args.slug, name=args.name, keywords=keywords,
        reply_tone=args.reply_tone or "业内人士",
        reply_style=args.reply_style or "亲切专业",
    )
    print(f"行业已创建: {path}")


def cmd_list(args):
    """列出行业"""
    slugs = list_industries()
    if not slugs:
        print("暂无行业配置")
        return
    for s in slugs:
        ind = load_industry(s)
        print(f"  [{s}] {ind.name} 关键词={ind.keywords}")


def cmd_collect(args):
    """采集: 博主发现 + 评论收集 + LLM 分类 + 入队"""
    industry = load_industry(args.industry)
    init()

    _run_collect_once(industry, args)
    bs = blogger_stats(industry.slug)

    # ── Loop mode: re-run every N minutes ──
    if args.loop:
        interval = int(args.loop) * 60
        log.info(f"定时模式启动: 每 {args.loop} 分钟采集一次 (Ctrl+C 停止)")
        iteration = 1
        try:
            while True:
                time.sleep(interval)
                iteration += 1
                log.info(f"=== 第 {iteration} 轮 ===")
                _run_collect_once(industry, args)
        except KeyboardInterrupt:
            log.info(f"定时模式停止，共 {iteration} 轮")


def _run_collect_once(industry, args):
    from core.discover import run_discovery
    comments = asyncio.run(run_discovery(
        industry,
        max_authors=args.max_authors,
        video_age_days=args.video_age,
        skip_discover=args.skip_discover,
        crawldir=args.crawldir or None,
    ))
    if not comments:
        log.info("无候选评论")
        return
    passed = classify_batch(comments, industry)
    count = enqueue_classified(passed)
    s = queue_stats(industry.slug)
    bs = blogger_stats(industry.slug)
    log.info(f"入队 {count} 条 | 博主 {bs['active']} active | 队列 {s['pending']} pending")


_initialized = False

def init():
    """初始化数据库连接和模型 (仅首次执行)"""
    global _initialized
    if _initialized:
        return
    from server.models import Base, engine
    from server.services.migrations import initialize_database
    initialize_database(Base, engine)
    _initialized = True


def cmd_send(args):
    """发送: AutoGLM DM 拦截"""
    industry = load_industry(args.industry)
    init()
    reclaim_stale_claims(1)

    devices = [d.strip() for d in args.devices.split(",")] if args.devices else None
    s = queue_stats(industry.slug)
    log.info(f"队列: {s['pending']} pending, {s['done']} done")
    run_senders(industry, devices)


def cmd_run(args):
    """全自动: 采集 + 发送"""
    cmd_collect(args)
    cmd_send(args)


def cmd_stats(args):
    """查看状态"""
    init()
    sys_cfg = load_system()

    if args.industry:
        s = queue_stats(args.industry)
        bs = blogger_stats(args.industry)
        print(f"行业 [{args.industry}]:")
        print(f"  博主: {bs['total']} total, {bs['active']} active")
        print(f"  队列: {s['total']} total, {s['pending']} pending, "
              f"{s['done']} done, {s['failed']} failed")
    else:
        s = queue_stats()
        print(f"全局队列: {s['total']} total, {s['pending']} pending")
        for d in sys_cfg.get("devices", []):
            from datetime import date
            st = get_consumer_state(d["id"]) or {}
            today = str(date.today())
            ds = st.get("daily_sent", 0) if st.get("last_sent_date") == today else 0
            print(f"  [{d['id']}] {ds}/{st.get('daily_limit', 0)} today "
                  f"({st.get('total_sent', 0)} ok / {st.get('total_failed', 0)} fail)")


def cmd_bloggers(args):
    """博主管理"""
    init()
    if args.list:
        bloggers = get_bloggers("all", args.industry or "")
        if not bloggers:
            print("暂无博主")
            return
        for b in bloggers:
            print(f"  [{b['status']}] {b['nickname']} {b['sec_uid'][:30]}... "
                  f"via:{b['source_keyword']}")
    elif args.add:
        sec_uid, nickname = args.add
        ok = add_blogger(sec_uid, nickname, industry_slug=args.industry or "")
        print(f"{'OK' if ok else '已存在'}: {nickname}")
    elif args.pause:
        ok = set_blogger_status(args.pause, "paused", args.industry or "")
        print(f"{'OK' if ok else '失败'}: pause {args.pause}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="雷霆捕获系统")
    sub = parser.add_subparsers(dest="command")

    # create
    p = sub.add_parser("create-industry")
    p.add_argument("--slug", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--keywords", required=True)
    p.add_argument("--reply-tone")
    p.add_argument("--reply-style")

    # list
    sub.add_parser("list-industries")

    # collect
    p = sub.add_parser("collect")
    p.add_argument("--industry", "-i", required=True)
    p.add_argument("--max-authors", type=int, default=12)
    p.add_argument("--video-age", type=int, default=7)
    p.add_argument("--skip-discover", action="store_true",
                   help="跳过博主发现，只增量采集已有博主的评论")
    p.add_argument("--crawldir", default="data",
                   help="检查点目录（支持断点续传，默认 data/）")
    p.add_argument("--loop", metavar="N",
                   help="定时循环：每 N 分钟执行一次采集 (Ctrl+C 停止)")

    # send
    p = sub.add_parser("send")
    p.add_argument("--industry", "-i", required=True)
    p.add_argument("--devices", "-d", help="设备ID列表，逗号分隔")

    # run (collect + send)
    p = sub.add_parser("run")
    p.add_argument("--industry", "-i", required=True)
    p.add_argument("--max-authors", type=int, default=12)
    p.add_argument("--video-age", type=int, default=7)
    p.add_argument("--skip-discover", action="store_true",
                   help="跳过博主发现，只增量采集已有博主的评论")
    p.add_argument("--devices", "-d")
    p.add_argument("--crawldir", default="data",
                   help="检查点目录（支持断点续传，默认 data/）")
    p.add_argument("--loop", metavar="N",
                   help="定时循环：每 N 分钟执行一次采集 (Ctrl+C 停止)")

    # stats
    p = sub.add_parser("stats")
    p.add_argument("--industry", "-i")

    # bloggers
    p = sub.add_parser("bloggers")
    p.add_argument("--industry", "-i")
    p.add_argument("--list", action="store_true")
    p.add_argument("--add", nargs=2, metavar=("SEC_UID", "NICKNAME"))
    p.add_argument("--pause", metavar="SEC_UID")

    args = parser.parse_args()

    cmds = {"create-industry": cmd_create, "list-industries": cmd_list,
            "collect": cmd_collect, "send": cmd_send, "run": cmd_run,
            "stats": cmd_stats, "bloggers": cmd_bloggers}

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()
