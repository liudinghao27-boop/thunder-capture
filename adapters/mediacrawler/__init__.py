"""MediaCrawler adapter.

Wraps the MediaCrawler subprocess (deps/MediaCrawler/) behind a clean interface.
Currently calls main.py via asyncio.create_subprocess_exec.

Future: replace subprocess with direct Python API when MediaCrawler
exports a programmatic interface.
"""
