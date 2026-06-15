"""配置加载器 — YAML 驱动，行业无关"""

import os
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


def _resolve_env(value):
    """Recursively resolve ${VAR} placeholders in strings."""
    if isinstance(value, str):
        def _replace(m):
            return os.getenv(m.group(1), "")
        return re.sub(r'\$\{(\w+)\}', _replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


@dataclass
class IndustryConfig:
    name: str
    slug: str
    keywords: list[str]
    reply_tone: str
    reply_style: str
    categories: list[str]
    reply_hook: str = ""
    daily_limit: int = 15
    video_max_age_days: int = 14
    comment_max_age_hours: int = 48
    platforms: list[str] = field(default_factory=lambda: ["douyin"])
    # SaaS fields (optional — not in YAML, set by server layer)
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    intent_keywords: list[str] = field(default_factory=list)
    noise_keywords: list[str] = field(default_factory=list)
    deepseek_key: str = ""
    zhipu_key: str = ""
    openai_key: str = ""
    target_users: list[str] = field(default_factory=list)
    user_id: str = ""
    matrix_target_devices: int = 30
    lead_inventory_days: int = 3
    global_daily_limit: int = 0
    auto_replenish_enabled: bool = False
    replenish_threshold_days: int = 1
    keyword_batch_size: int = 12
    collect_authors_per_run: int = 60
    collect_video_limit: int = 120
    compliance_mode: bool = False
    webhook_url: str = ""
    auto_export_enabled: bool = False


def load_system() -> dict:
    cfg_path = CONFIG_DIR / "system.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"系统配置不存在: {cfg_path}\n"
            f"请复制 system.example.yaml → system.yaml 并填入真实值"
        )
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Resolve ${VAR} placeholders and env overrides
    cfg = _resolve_env(cfg)
    if os.getenv("THUNDER_DEEPSEEK_KEY"):
        cfg.setdefault("api_keys", {})["deepseek"] = os.getenv("THUNDER_DEEPSEEK_KEY")
    if os.getenv("THUNDER_ZHIPU_KEY"):
        cfg.setdefault("api_keys", {})["zhipu"] = os.getenv("THUNDER_ZHIPU_KEY")
    return cfg


def load_industry(slug: str) -> IndustryConfig:
    path = CONFIG_DIR / "industries" / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"行业配置不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return IndustryConfig(**{k: v for k, v in data.items()
                             if k in IndustryConfig.__dataclass_fields__})


def list_industries() -> list[str]:
    """列出所有已配置的行业 slug"""
    dir_path = CONFIG_DIR / "industries"
    slugs = []
    for p in dir_path.glob("*.yaml"):
        if p.name.startswith("_"):
            continue
        slugs.append(p.stem)
    return sorted(slugs)


def create_industry(slug: str, name: str, keywords: list[str],
                    reply_tone: str = "业内人士",
                    reply_style: str = "亲切专业",
                    categories: list[str] = None,
                    daily_limit: int = 15,
                    platforms: list[str] = None) -> Path:
    """新建行业配置文件"""
    path = CONFIG_DIR / "industries" / f"{slug}.yaml"
    if path.exists():
        raise FileExistsError(f"行业 {slug} 已存在")
    data = {
        "name": name,
        "slug": slug,
        "keywords": keywords,
        "reply_tone": reply_tone,
        "reply_style": reply_style,
        "categories": categories or ["咨询类", "其他"],
        "daily_limit": daily_limit,
        "platforms": platforms or ["douyin"],
        "video_max_age_days": 14,
        "comment_max_age_hours": 48,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    return path
