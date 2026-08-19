"""Run the new relationship measurement paths against the production database.

This is the "after" half of the before/after evidence. The new paths cannot be
observed through the deployed API, because the deployed release predates them
and deploying is explicitly out of scope for this change. So they are executed
here against the same production data the deployed backend reads, and their
output is recorded as evidence of what the audit *would* report once the
release carrying them ships.

Safety: the session is opened read-only and every statement runs inside a
``SET TRANSACTION READ ONLY`` block that is rolled back. PostgreSQL rejects any
write attempted in such a transaction, so this cannot mutate scientific data
even if a measurement were wrong about what it is doing.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.readiness.relationship_measurement import (
    measure_declared_relationships,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OUT_PATH = os.environ.get(
    "RELATIONSHIP_EVIDENCE_PATH", "production-relationship-measurement.json"
)


def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL is not set; cannot measure against production.")
        return 1

    started = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            results = measure_declared_relationships(cur)
        conn.rollback()

    totals: dict[str, int] = {}
    for r in results.values():
        totals[r["state"]] = totals.get(r["state"], 0) + 1

    evidence = {
        "contract": "OCU-PRODUCTION-RELATIONSHIP-MEASUREMENT-001",
        "captured_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "access": "read_only_transaction_rolled_back",
        "note": (
            "Executed against the production database using the measurement paths "
            "added in this branch. The deployed release does not yet carry them; "
            "this records what the audit would report once it does."
        ),
        "relationships": results,
        "state_totals": totals,
        "source_warnings": [
            {"relationship": name, "warning": w}
            for name, r in results.items()
            for w in (r.get("source_warnings") or [])
        ],
    }

    with open(OUT_PATH, "w") as fh:
        json.dump(evidence, fh, indent=2)

    for name, r in results.items():
        line = f"  {name:32s} {r['state']:12s}"
        if r["state"] in {"present", "absent"}:
            line += (
                f" {r['object_table']}"
                f"  rows={r['rows_matching_taxonomy']:,}"
                f"  taxa={r['taxa_reached']:,}"
                f"  via={r['measurement']}"
            )
        else:
            line += f" {r.get('detail', '')[:110]}"
        print(line)
    print()
    print(f"state totals: {totals}")
    for w in evidence["source_warnings"]:
        print(f"  WARNING [{w['relationship']}] {w['warning']}")
    print(f"evidence written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
