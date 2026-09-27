"""Society CRM backup/restore drill (OC-CRM-BACKUP-RESTORE-001).

Dumps the CRM schemas from ``--source-dsn`` with pg_dump (custom format, one
consistent snapshot), restores into a freshly created, uniquely named scratch
database via ``--admin-dsn``, and verifies that every row, digest, RLS policy,
trigger, constraint, and sequence survived, then exercises tenant isolation and
append-only guards in the restored copy. The source is only read.

Exit codes: 0 = drill passed; 1 = drill ran and found discrepancies/failures;
2 = drill could not run (configuration, connectivity, missing binaries).

Connection strings are never printed with passwords.
See docs/operations/OC-CRM-BACKUP-RESTORE-001.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.constituent_platform.backup_verification import (  # noqa: E402
    DEFAULT_SCHEMAS,
    RestoreDrillError,
    redact_text,
    run_backup_restore_drill,
    validate_schemas,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-dsn", default=os.environ.get("DATABASE_URL"),
                        help="database to back up (default: $DATABASE_URL); only read")
    parser.add_argument("--admin-dsn", default=None,
                        help="connection allowed to CREATE/DROP DATABASE for the scratch restore "
                             "(default: same cluster as --source-dsn)")
    parser.add_argument("--schemas", default=",".join(DEFAULT_SCHEMAS),
                        help="comma-separated CRM schemas to dump and verify (default: %(default)s)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch database for inspection")
    parser.add_argument("--dump-path", default=None, help="keep the pg_dump file at this path")
    parser.add_argument("--output", default=None, help="write the JSON report to this file")
    parser.add_argument("--pg-dump-bin", default=None, help="pg_dump binary (default: $PG_DUMP_BIN or discovered)")
    parser.add_argument("--pg-restore-bin", default=None,
                        help="pg_restore binary (default: $PG_RESTORE_BIN or discovered)")
    parser.add_argument("--isolation-org-limit", type=int, default=20,
                        help="max organizations to exercise in the isolation check (default: %(default)s)")
    return parser


def _summary(report: dict) -> str:
    lines = [
        f"OC-CRM-BACKUP-RESTORE-001: {'PASS' if report['pass'] else 'FAIL'}",
        f"  source: {report['source']}",
        f"  scratch database: {report['scratch_database']}"
        + (" (kept)" if report.get("scratch_database_kept") else " (dropped)" if report.get("scratch_database_dropped") else ""),
        f"  tables: {report.get('table_count')}  rows: {report.get('total_source_rows')}  dump bytes: {report.get('dump_bytes')}",
    ]
    checks = report.get("checks", {})
    for name in ("roles", "isolation", "append_only_guards"):
        if name in checks:
            lines.append(f"  check {name}: {checks[name]['status']}")
    for entry in report.get("discrepancies", []):
        if entry["severity"] == "error":
            lines.append(f"  [error] {entry['message']}")
    for warning in report.get("warnings", []):
        lines.append(f"  [warning] {warning}")
    for name in ("roles", "isolation", "append_only_guards"):
        for failure in checks.get(name, {}).get("failures", []) or []:
            lines.append(f"  [error] {failure}")
    if checks.get("roles", {}).get("missing_roles"):
        lines.append(f"  [error] missing roles in target cluster: {', '.join(checks['roles']['missing_roles'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.source_dsn:
        print("error: --source-dsn or DATABASE_URL is required", file=sys.stderr)
        return 2
    try:
        schemas = validate_schemas(args.schemas.split(","))
        report = run_backup_restore_drill(
            args.source_dsn,
            args.admin_dsn,
            schemas,
            args.pg_dump_bin,
            args.pg_restore_bin,
            keep=args.keep,
            dump_path=args.dump_path,
            isolation_org_limit=args.isolation_org_limit,
        )
    except (RestoreDrillError, ValueError, OSError) as exc:
        print(f"error: drill could not run: {redact_text(str(exc))}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - driver errors: report redacted, never a traceback with a DSN
        print(f"error: drill could not run: {type(exc).__name__}: {redact_text(str(exc))}", file=sys.stderr)
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(_summary(report))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
