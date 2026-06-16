"""Server configuration."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("THUNDER_SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

DATABASE_URL = os.getenv(
    "THUNDER_DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'data' / 'thunder.db'}",
)

# API keys: env var overrides system.yaml
DEEPSEEK_KEY = os.getenv("THUNDER_DEEPSEEK_KEY", "")
ZHIPU_KEY = os.getenv("THUNDER_ZHIPU_KEY", "")
