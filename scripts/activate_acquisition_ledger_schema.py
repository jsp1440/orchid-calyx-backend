"""Preflight or explicitly apply the acquisition-ledger schema migration.

Default behaviour is read-only: it connects to the database the application
uses (``app.database.get_database_url``: ``PGHOST`` first, then
``DATABASE_URL``), runs the ledger's own fail-closed schema check and reports
what is missing. Nothing is written.

Mutation requires BOTH ``--apply`` and
``CALYX_ACQUISITION_LEDGER_MIGRATION_CONFIRM=APPLY_ACQUISITION_LEDGER``. The
migration (``migrations/20260930_acquisition_ledger.sql``) is additive and
idempotent and runs in one transaction; the schema check is re-run afterwards
and the run fails unless it passes. Applying it to production is an owner
deployment action. No provider call is made and no ledger row is touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIRM_ENV = "CALYX_ACQUISITION_LEDGER_MIGRATION_CONFIRM"
CONFIRMATION = "APPLY_ACQUISITION_LEDGER"
EVIDENCE_ENV = "CALYX_ACQUISITION_LEDGER_MIGRATION_EVIDENCE_PATH"


def _write(report: dict[str, Any]) -> None:
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    report["artifact_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    rendered = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    evidence_path = os.environ.get(EVIDENCE_ENV, "").strip()
    if evidence_path:
        Path(evidence_path).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def _sqlalchemy_url(url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def run(*, apply_requested: bool) -> int:
    from sqlalchemy import create_engine

    from app.database import get_database_url
    from app.source_federation.acquisition_ledger_schema import (
        MIGRATION_ID,
        MIGRATION_PATH,
        apply_ledger_migration,
        ledger_schema_problems,
    )

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply_requested else "preflight",
        "migration_id": MIGRATION_ID,
        "migration_sha256": hashlib.sha256(MIGRATION_PATH.read_bytes()).hexdigest(),
        "database_source": "PGHOST"
        if os.environ.get("PGHOST")
        else ("DATABASE_URL" if os.environ.get("DATABASE_URL") else "none"),
        "apply_requested": apply_requested,
        "explicit_confirmation_present": os.environ.get(CONFIRM_ENV, "")
        == CONFIRMATION,
        "database_mutation_attempted": False,
        "provider_calls": 0,
    }
    blockers: list[str] = []
    url = get_database_url()
    if not url.startswith(("postgres://", "postgresql")):
        blockers.append("POSTGRESQL_DATABASE_REQUIRED")
        report.update({"blockers": blockers, "status": "blocked"})
        _write(report)
        return 2
    if apply_requested and not report["explicit_confirmation_present"]:
        blockers.append("EXPLICIT_APPLY_CONFIRMATION_REQUIRED")

    engine = create_engine(_sqlalchemy_url(url), pool_pre_ping=True)
    try:
        try:
            with engine.connect() as connection:
                report["problems_before"] = list(ledger_schema_problems(connection))
            report["migration_required"] = bool(report["problems_before"])
            if apply_requested and not blockers:
                report["database_mutation_attempted"] = True
                with engine.begin() as connection:
                    apply_ledger_migration(connection)
        except Exception as exc:  # noqa: BLE001 - reported as a typed blocker
            blockers.append(f"DATABASE_OPERATION_FAILED:{type(exc).__name__}")
        try:
            with engine.connect() as connection:
                report["problems_after"] = list(ledger_schema_problems(connection))
        except Exception as exc:  # noqa: BLE001 - reported as a typed blocker
            blockers.append(f"POST_CHECK_FAILED:{type(exc).__name__}")
    finally:
        engine.dispose()

    schema_ready = report.get("problems_after") == []
    report["schema_ready"] = schema_ready
    if apply_requested and not schema_ready:
        blockers.append("POST_APPLY_SCHEMA_CHECK_FAILED")
    report["blockers"] = sorted(set(blockers))
    report["status"] = "passed" if not blockers else "blocked"
    report["applied"] = bool(
        apply_requested and report["database_mutation_attempted"] and schema_ready
    )
    _write(report)
    return 0 if not blockers else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return run(apply_requested=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
