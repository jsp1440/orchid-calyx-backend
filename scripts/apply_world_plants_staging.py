"""Apply and verify the World Plants staging migration.

This script is intended for an explicitly approved production-environment workflow.
It fails closed and never promotes a taxonomy release.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

MIGRATION = Path("migrations/WORLD-PLANTS-STAGING-001.sql")
EXPECTED_TABLES = {
    "world_plants_releases",
    "world_plants_rows",
    "world_plants_photos",
    "world_plants_deltas",
    "world_plants_promotion_receipts",
}


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL_REQUIRED")
    return value


def verify_tables(connection: psycopg.Connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'oc_source'
            """
        )
        return {row[0] for row in cursor.fetchall()}


def main() -> int:
    if not MIGRATION.is_file():
        print(f"FAIL migration_missing: {MIGRATION}")
        return 1

    try:
        database_url = _database_url()
        sql = MIGRATION.read_text(encoding="utf-8")
        with psycopg.connect(database_url, autocommit=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                cursor.execute(sql)  # Required idempotency proof.
            connection.commit()
            observed = verify_tables(connection)
    except Exception as exc:  # noqa: BLE001 - operator script must report and fail closed.
        print(f"FAIL staging_migration: {type(exc).__name__}: {exc}")
        return 1

    missing = EXPECTED_TABLES - observed
    if missing:
        print(f"FAIL staging_schema_missing_tables: {sorted(missing)}")
        return 1

    print(f"PASS staging_schema_verified: {sorted(EXPECTED_TABLES)}")
    print("NOTE verification flag must be set by the deployment operator after this proof.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
