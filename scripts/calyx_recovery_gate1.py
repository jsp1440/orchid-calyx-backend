"""Gate 1 of CALYX-RECOVERY-001: read-only recovery baseline.

SELECT statements only. This script never writes, never migrates, never
activates, and never prints a connection string or any credential — it reports
the database's identity by name and host only, which is what a receipt needs.

Every field is classified WORKING / DEGRADED / BLOCKED / UNKNOWN. A field that
could not be measured is UNKNOWN, never zero: "we could not look" and "there
is nothing there" are different statements, and only one of them is about the
Continuum's data.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

WORKING = "WORKING"
DEGRADED = "DEGRADED"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"

#: (label, schema-qualified relation) for the coverage counts Gate 1 asks for.
#: Counted only if the relation exists; a missing relation is UNKNOWN, because
#: this script cannot tell "not deployed here" from "named differently".
COVERAGE_TARGETS = (
    ("build051_research_requests", "oc_admin", "build051_research_requests"),
    ("research_station_records", "oc_admin", "research_station_records"),
)


def _classify(available: bool, present: bool) -> str:
    if not available:
        return BLOCKED
    return WORKING if present else DEGRADED


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    receipt: dict[str, object] = {
        "gate": "CALYX-RECOVERY-001/gate-1",
        "generated_at": started,
        "repository_sha": os.environ.get("GITHUB_SHA", UNKNOWN),
        "read_only": True,
        "fields": {},
    }
    fields: dict[str, object] = receipt["fields"]  # type: ignore[assignment]

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        fields["database_connectivity"] = {
            "state": BLOCKED,
            "detail": "DATABASE_URL is not configured for this run",
        }
        # Everything downstream is unmeasurable, and says so rather than zero.
        for label, _, _ in COVERAGE_TARGETS:
            fields[label] = {"state": UNKNOWN, "detail": "no database connection"}
        json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        fields["database_connectivity"] = {
            "state": BLOCKED,
            "detail": f"psycopg unavailable: {exc}",
        }
        json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Identity by name only. The connection string never appears.
                cur.execute(
                    "SELECT current_database() AS db, current_user AS usr, version() AS v"
                )
                identity = cur.fetchone() or {}
                fields["database_connectivity"] = {"state": WORKING}
                fields["database_identity"] = {
                    "state": WORKING,
                    "database": identity.get("db"),
                    "user": identity.get("usr"),
                    "server_version": str(identity.get("v", ""))[:40],
                }

                for label, schema, table in COVERAGE_TARGETS:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                        ) AS present
                        """,
                        (schema, table),
                    )
                    present = bool((cur.fetchone() or {}).get("present"))
                    entry: dict[str, object] = {
                        "state": _classify(True, present),
                        "relation": f"{schema}.{table}",
                        "present": present,
                    }
                    if present:
                        cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.{table}")
                        entry["row_count"] = int((cur.fetchone() or {}).get("n", 0))
                    else:
                        # Absent relation: the row count is unknown, not zero.
                        entry["row_count"] = None
                        entry["detail"] = "relation not found in this database"
                    fields[label] = entry

                # Request states, so the executor's queue depth is measurable
                # without reading any request's content.
                if fields.get("build051_research_requests", {}).get("present"):  # type: ignore[union-attr]
                    cur.execute(
                        """
                        SELECT payload->>'status' AS status, COUNT(*) AS n
                        FROM oc_admin.build051_research_requests
                        GROUP BY 1 ORDER BY 1
                        """
                    )
                    fields["research_request_states"] = {
                        "state": WORKING,
                        "counts": {
                            str(row["status"]): int(row["n"]) for row in cur.fetchall()
                        },
                    }
                else:
                    fields["research_request_states"] = {
                        "state": UNKNOWN,
                        "detail": "request table not present",
                    }
    except Exception as exc:
        # The exception type and message only. A psycopg error can carry the
        # host; the class name and a truncated message do not carry secrets.
        fields["database_connectivity"] = {
            "state": BLOCKED,
            "detail": f"{type(exc).__name__}",
        }
        for label, _, _ in COVERAGE_TARGETS:
            fields.setdefault(label, {"state": UNKNOWN, "detail": "connection failed"})

    json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
