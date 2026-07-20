"""Serialize validation scripts that share the configured PostgreSQL database."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import psycopg

ALLOWED = {
    "build_078_postgres_validation.py",
    "build_079_postgres_validation.py",
    "build_082a_live_validation.py",
}
LOCK_ID = 82078079


def main() -> None:
    if len(sys.argv) != 2 or Path(sys.argv[1]).name not in ALLOWED:
        raise SystemExit("approved validation script required")
    target = Path(sys.argv[1]).resolve()
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            runpy.run_path(str(target), run_name="__main__")
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


if __name__ == "__main__":
    main()
