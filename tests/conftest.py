"""Pytest configuration: force SQLite test DB before server modules import."""

import os
import sys

import pytest

# Must set before any server module imports a DB engine
os.environ.setdefault("THUNDER_DATABASE_URL", "sqlite:///./data/test_thunder.db")

# Ensure a clean test database for each test run
_test_db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "test_thunder.db"))
for suffix in ("", "-shm", "-wal"):
    try:
        os.remove(_test_db_path + suffix)
    except FileNotFoundError:
        pass

# Ensure project root is on path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(autouse=True)
def _mock_socket_gethostbyname(monkeypatch):
    """Provide deterministic public DNS resolution for webhook URL tests."""
    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda _hostname: "8.8.8.8")
