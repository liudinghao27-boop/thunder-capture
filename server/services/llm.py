"""LLM client factory — switch between DeepSeek, Zhipu, OpenAI."""

import os
from openai import OpenAI


def get_llm_client(provider: str = "deepseek", model: str = "deepseek-chat") -> OpenAI:
    """Return an OpenAI-compatible client for the given provider."""
    provider = provider.lower()

    if provider == "deepseek":
        key = os.getenv("THUNDER_DEEPSEEK_KEY", "")
        base = "https://api.deepseek.com"
    elif provider == "zhipu":
        key = os.getenv("THUNDER_ZHIPU_KEY", "")
        base = "https://open.bigmodel.cn/api/paas/v4"
    elif provider == "openai":
        key = os.getenv("THUNDER_OPENAI_KEY", "")
        base = os.getenv("THUNDER_OPENAI_BASE", "https://api.openai.com/v1")
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

    if not key:
        # Fallback to system.yaml
        try:
            from engine.config import load_system
            sys_cfg = load_system()
            if provider == "deepseek":
                key = sys_cfg["api_keys"]["deepseek"]
            elif provider == "zhipu":
                key = sys_cfg["api_keys"]["zhipu"]
        except Exception:
            pass

    if not key:
        raise ValueError(f"No API key found for {provider}")

    return OpenAI(base_url=base, api_key=key)
