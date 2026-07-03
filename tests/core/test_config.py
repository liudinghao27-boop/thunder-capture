"""Tests for core.config loading and caching."""

import pytest

from core import config as config_module
from core.config import load_system


@pytest.fixture(autouse=True)
def _reset_config_cache(tmp_path, monkeypatch):
    """Point config loader at a temporary system.yaml and clear its cache."""
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("THUNDER_DEEPSEEK_KEY", raising=False)
    monkeypatch.delenv("THUNDER_ZHIPU_KEY", raising=False)
    monkeypatch.delenv("THUNDER_OPENAI_KEY", raising=False)
    monkeypatch.delenv("THUNDER_RELOAD_CONFIG", raising=False)
    config_module._cached_load_system.cache_clear()
    yield
    config_module._cached_load_system.cache_clear()


def _write_system_yaml(tmp_path, content: str) -> None:
    (tmp_path / "system.yaml").write_text(content, encoding="utf-8")


def test_load_system_reads_yaml(tmp_path, monkeypatch):
    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: old-key\n")
    cfg = load_system()
    assert cfg["api_keys"]["deepseek"] == "old-key"


def test_load_system_caches_parsed_yaml(tmp_path, monkeypatch):
    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: cached-key\n")
    call_count = {"n": 0}
    original = config_module._load_system_raw

    def _counting_raw():
        call_count["n"] += 1
        return original()

    monkeypatch.setattr(config_module, "_load_system_raw", _counting_raw)

    c1 = load_system()
    c2 = load_system()
    assert c1 == c2
    assert call_count["n"] == 1


def test_load_system_returns_isolated_copies(tmp_path, monkeypatch):
    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: key\n")
    cfg = load_system()
    cfg["extra"] = "mutated"
    cfg2 = load_system()
    assert "extra" not in cfg2


def test_load_system_force_reload(tmp_path, monkeypatch):
    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: first\n")
    assert load_system()["api_keys"]["deepseek"] == "first"

    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: second\n")
    assert load_system()["api_keys"]["deepseek"] == "first"  # still cached
    assert load_system(force_reload=True)["api_keys"]["deepseek"] == "second"


def test_load_system_env_reload_flag(tmp_path, monkeypatch):
    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: first\n")
    assert load_system()["api_keys"]["deepseek"] == "first"

    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: second\n")
    monkeypatch.setenv("THUNDER_RELOAD_CONFIG", "1")
    assert load_system()["api_keys"]["deepseek"] == "second"


def test_load_system_env_override(tmp_path, monkeypatch):
    _write_system_yaml(tmp_path, "api_keys:\n  deepseek: yaml-key\n")
    monkeypatch.setenv("THUNDER_DEEPSEEK_KEY", "env-key")
    cfg = load_system()
    assert cfg["api_keys"]["deepseek"] == "env-key"


def test_load_system_openai_env_override(tmp_path, monkeypatch):
    _write_system_yaml(tmp_path, "api_keys:\n  openai: yaml-openai\n")
    monkeypatch.setenv("THUNDER_OPENAI_KEY", "env-openai")
    cfg = load_system()
    assert cfg["api_keys"]["openai"] == "env-openai"
