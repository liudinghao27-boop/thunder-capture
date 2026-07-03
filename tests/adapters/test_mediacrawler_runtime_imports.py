import importlib
import sys
from pathlib import Path


def test_mediacrawler_main_imports_without_optional_platform_dependencies(monkeypatch):
    mc_dir = Path(__file__).resolve().parents[2] / "deps" / "MediaCrawler"
    monkeypatch.syspath_prepend(str(mc_dir))
    sys.modules.pop("main", None)

    module = importlib.import_module("main")

    assert hasattr(module, "CrawlerFactory")
