"""Run server database migrations explicitly."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.models import Base, engine  # noqa: E402
from server.services.migrations import initialize_database, verify_matrix_schema  # noqa: E402


def main():
    added = initialize_database(Base, engine)
    matrix = verify_matrix_schema(engine)
    print("Database migrations complete.")
    print("Added columns:", ", ".join(added) if added else "none")
    print("Matrix schema:", "ok" if matrix["ok"] else f"missing {matrix['missing_tables']}")


if __name__ == "__main__":
    main()
