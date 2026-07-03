"""LLM client factory — unified singleton across engine + server.

All LLM client creation flows through this module to avoid duplicated
configuration and global-state bugs. Supports DeepSeek, Zhipu, OpenAI,
and any OpenAI-compatible provider.
"""

import os
import threading
from typing import Any, Optional
from pathlib import Path
from dotenv import load_dotenv

import httpx
from openai import OpenAI

# Load dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

# ── Provider registry ──────────────────────────────────

_PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "env_key": "THUNDER_DEEPSEEK_KEY",
        "yaml_key": ("api_keys", "deepseek"),
        "base_url": "https://api.deepseek.com",
    },
    "zhipu": {
        "env_key": "THUNDER_ZHIPU_KEY",
        "yaml_key": ("api_keys", "zhipu"),
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
    "openai": {
        "env_key": "THUNDER_OPENAI_KEY",
        "yaml_key": None,
        "base_url": "https://api.openai.com/v1",
    },
}

# ── Thread-safe singleton cache ────────────────────────

_client_cache: dict[str, OpenAI] = {}
_cache_lock = threading.Lock()


def _resolve_api_key(provider: str) -> str:
    """Resolve API key: env var → system.yaml → error."""
    info = _PROVIDERS.get(provider)
    if not info:
        raise ValueError(f"Unknown LLM provider: {provider}")

    # 1. Environment variable
    key = os.getenv(info["env_key"], "")
    if key:
        return key

    # 2. Fallback to system.yaml
    yk = info.get("yaml_key")
    if yk:
        try:
            from core.config import load_system
            cfg = load_system()
            section, field = yk
            key = str(cfg.get(section, {}).get(field, ""))
        except Exception:
            pass

    if key:
        return key

    # 3. Provider-specific base env override
    base_env = os.getenv("THUNDER_OPENAI_BASE", "")
    if provider == "openai" and base_env:
        return os.getenv("THUNDER_OPENAI_KEY", "")

    raise ValueError(
        f"No API key found for provider '{provider}'. "
        f"Set {info['env_key']} environment variable or configure system.yaml."
    )


def get_llm_client(
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    *,
    api_key: Optional[str] = None,
    timeout: float = 60.0,
    connect_timeout: float = 10.0,
    force_new: bool = False,
) -> OpenAI:
    """Return an OpenAI-compatible client (thread-safe, cached).

    Args:
        provider: One of 'deepseek', 'zhipu', 'openai'.
        model: Model name (informational — not used for auth).
        api_key: Optional key override.
        timeout: Request timeout in seconds.
        connect_timeout: Connection timeout in seconds.
        force_new: If True, create a new client even if cached.
    """
    provider = provider.lower()
    info = _PROVIDERS.get(provider)
    if not info:
        raise ValueError(f"Unknown LLM provider: {provider}")

    key = api_key if api_key else _resolve_api_key(provider)
    base_url = info["base_url"]
    if provider == "openai":
        base_url = os.getenv("THUNDER_OPENAI_BASE", base_url)
    cache_key = f"{provider}:{base_url}:{key[:8]}"

    with _cache_lock:
        if not force_new and cache_key in _client_cache:
            return _client_cache[cache_key]

        client = OpenAI(
            base_url=base_url,
            api_key=key,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
        )
        _client_cache[cache_key] = client
        return client


def clear_client_cache():
    """Clear cached LLM clients (useful for testing or key rotation)."""
    with _cache_lock:
        _client_cache.clear()


# ── Convenience shortcuts ───────────────────────────────

def get_deepseek_client() -> OpenAI:
    """Get cached DeepSeek client."""
    return get_llm_client("deepseek")


def get_zhipu_client() -> OpenAI:
    """Get cached Zhipu (GLM) client."""
    return get_llm_client("zhipu")
