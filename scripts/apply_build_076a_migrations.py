"""Apply the BUILD-070 and BUILD-076A intake migrations safely.

Usage (for example from a Render shell):
    python scripts/apply_build_076a_migrations.py

The script uses DATABASE_URL, runs both additive/idempotent SQL migrations in a
single transaction, and verifies the three BUILD-076A tables before committing.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    ROOT / "migrations" / "070_knowledge_intake.sql",
    ROOT / "migrations" / "076a_universal_intake.sql",
)
REQUIRED_TABLES = (
    "oc_intake.ingestion_batches",
    "oc_intake.documents",
    "oc_intake.document_events",
)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set; no database changes were made.")

    for path in MIGRATIONS:
        if not path.is_file():
            raise SystemExit(f"Required migration is missing: {path}")

    with psycopg.connect(database_url) as conn:
        try:
            with conn.cursor() as cur:
                for path in MIGRATIONS:
                    print(f"Applying {path.relative_to(ROOT)}...")
                    cur.execute(path.read_text(encoding="utf-8"), prepare=False)

                missing: list[str] = []
                for table_name in REQUIRED_TABLES:
                    cur.execute("SELECT to_regclass(%s)", (table_name,))
                    if cur.fetchone()[0] is None:
                        missing.append(table_name)

                if missing:
                    raise RuntimeError(
                        "Migration verification failed; missing tables: "
                        + ", ".join(missing)
                    )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    print("BUILD-076A intake migrations applied and verified successfully.")


if __name__ == "__main__":
    main()
