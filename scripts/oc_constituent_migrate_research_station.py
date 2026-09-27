#!/usr/bin/env python3
"""Migrate constituent-platform records from Research Station to the canonical CRM schemas (#1652).

Dry run is the default and writes nothing; ``--apply`` writes. Re-running is
idempotent. Records whose canonical copy differs are reported as ``conflict``
and never overwritten; malformed legacy records are reported as ``invalid``.
The JSON report uses hashed emails and record ids only.

    DATABASE_URL=postgresql://... python scripts/oc_constituent_migrate_research_station.py            # dry run
    DATABASE_URL=postgresql://... python scripts/oc_constituent_migrate_research_station.py --apply
    ... --report /path/report.json      # also write the report to a file

Exit codes: 0 = every record reconciled with no conflict/invalid/failed;
2 = discrepancies reported (inspect the report); 1 = could not run.

Cutover: apply the migrations, run ``--apply``, re-run (dry run) and require
``cutover_ready: true``, then set ``OC_CONSTITUENT_PERSISTENCE=canonical``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.constituent_platform import canonical_store as cs  # noqa: E402
from app.constituent_platform.research_station_migration import migrate  # noqa: E402
from app.constituent_platform.tenant_db import dsn_connection_factory  # noqa: E402
from runtime.research_station_store import PostgresProjectRecordStore  # noqa: E402


def read_only_db_execute(dsn: str):
    """A ``db_execute`` for the source store that can only read."""

    def db_execute(work):
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                return work(cur)

    return db_execute


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="apply", action="store_false", help="plan only, no writes (default)")
    mode.add_argument("--apply", dest="apply", action="store_true", help="write created records")
    parser.set_defaults(apply=False)
    parser.add_argument("--database-url", default=None, help="canonical database (default: $DATABASE_URL)")
    parser.add_argument(
        "--source-database-url", default=None, help="Research Station database (default: the canonical database)"
    )
    parser.add_argument("--organization-slug", default=cs.PLATFORM_ORG_SLUG)
    parser.add_argument("--report", type=Path, default=None, help="also write the JSON report here")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw = args.database_url or os.environ.get("DATABASE_URL", "")
    if not raw.strip():
        print("DATABASE_URL (or --database-url) is required", file=sys.stderr)
        return 1
    dsn = cs.normalized_dsn(raw)
    source_dsn = cs.normalized_dsn(args.source_database_url) if args.source_database_url else dsn
    try:
        report: dict[str, Any] = migrate(
            PostgresProjectRecordStore(read_only_db_execute(source_dsn)),
            connect=dsn_connection_factory(dsn),
            organization_slug=args.organization_slug,
            apply=args.apply,
        )
    except (cs.CanonicalStoreUnavailable, psycopg.Error) as exc:
        print(f"migration could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.report is not None:
        args.report.write_text(text + "\n", encoding="utf-8")
    counts = report["counts"]
    return 2 if counts["conflict"] or counts["invalid"] or counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
