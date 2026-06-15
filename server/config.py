"""Server configuration."""

import os
import secrets
import warnings
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

# ── Security: SECRET_KEY MUST be set via environment variable in production ──
_raw_key = os.getenv("THUNDER_SECRET_KEY", "")
if not _raw_key:
    if os.getenv("THUNDER_ENV", "").lower() == "production":
        raise RuntimeError(
            "THUNDER_SECRET_KEY must be set via environment variable in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    dev_key_path = BASE_DIR / "data" / ".thunder_secret_key"
    dev_key_path.parent.mkdir(parents=True, exist_ok=True)
    if dev_key_path.exists():
        _raw_key = dev_key_path.read_text(encoding="utf-8").strip()
    if not _raw_key:
        _raw_key = secrets.token_hex(32)
        dev_key_path.write_text(_raw_key, encoding="utf-8")
    warnings.warn(
        "THUNDER_SECRET_KEY not set — using persisted development key from "
        f"{dev_key_path}. Set THUNDER_SECRET_KEY in production!",
        RuntimeWarning,
    )
SECRET_KEY = _raw_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

DATABASE_URL = os.getenv(
    "THUNDER_DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'data' / 'thunder.db'}",
)

# API keys: env var overrides system.yaml
DEEPSEEK_KEY = os.getenv("THUNDER_DEEPSEEK_KEY", "")
ZHIPU_KEY = os.getenv("THUNDER_ZHIPU_KEY", "")

# ── CORS configuration ──
_CORS_ORIGINS = os.getenv("THUNDER_CORS_ORIGINS", "")
if _CORS_ORIGINS:
    CORS_ORIGINS = [o.strip() for o in _CORS_ORIGINS.split(",")]
else:
    # Development defaults — override in production via THUNDER_CORS_ORIGINS
    CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]
