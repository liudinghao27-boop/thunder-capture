"""Pytest configuration: force SQLite test DB before server modules import."""

import os
import sys

# Must set before any server module imports a DB engine
os.environ.setdefault("THUNDER_DATABASE_URL", "sqlite:///./data/test_thunder.db")

# Ensure project root is on path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
