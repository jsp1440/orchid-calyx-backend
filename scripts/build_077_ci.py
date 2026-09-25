"""Bootstrap only the fixed throwaway BUILD-077 pull-request database."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

CI_DATABASE_URL = "postgresql://postgres:postgres@localhost:55477/orchid_build077_test"
ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    "070_knowledge_intake.sql",
    "076a_universal_intake.sql",
    "076b_semantic_extraction.sql",
    "077_ontology_evidence_registry.sql",
)


def bootstrap() -> None:
    # Exact equality also rejects libpq query overrides, alternate hosts, and
    # accidental inheritance of the configured staging/production database.
    if os.environ.get("DATABASE_URL") != CI_DATABASE_URL:
        raise ValueError("BUILD077_CI_REQUIRES_FIXED_LOCAL_TEST_DATABASE")
    with psycopg.connect(CI_DATABASE_URL) as connection:
        for name in MIGRATIONS:
            connection.execute((ROOT / "migrations" / name).read_text(encoding="utf-8"))


def main() -> int:
    bootstrap()
    from scripts.build_077_postgres_validation import main as validate

    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
