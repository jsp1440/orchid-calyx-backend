"""Dry-run-by-default repair CLI for the two documented taxonomy-id gaps.

Fills ``orchid_taxonomy_id`` on rows in ``oc_interactions.orchid_interaction_edges``
and ``oc_mycorrhiza.orchid_fungal_associations`` where it is null but the row's
``orchid_scientific_name`` resolves deterministically and unambiguously against
``public.orchid_taxonomy`` (see ``app/readiness/taxonomy_id_repair.py`` for the
resolution policy and safety invariants).

Dry-run is the default and requires no write permission: measurement runs
inside ``SET TRANSACTION READ ONLY`` and is always rolled back, mirroring
``scripts/measure_relationships_against_production.py``. Writing requires both
``--execute`` and the exact confirmation token in
``CALYX_TAXONOMY_ID_REPAIR_CONFIRMATION``, mirroring
``scripts/upload_hassler_release_guarded.py``.

Never rewrites a populated ``orchid_taxonomy_id``, never touches
``partner_taxon_id`` / ``fungal_taxon_id``, and never resolves an ambiguous
name -- those rows are reported in a queue for human review instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.readiness.taxonomy_id_repair import (  # noqa: E402
    REPAIR_TARGETS,
    apply_repair_plan,
    build_repair_plan,
    generate_repair_sql,
    measure_repair_candidates,
)

EXECUTION_CONFIRMATION = "REPAIR-POLLINATOR-MYCORRHIZA-TAXONOMY-IDS-CONFIRMED"


def _targets_for(name: str):
    if name == "all":
        return REPAIR_TARGETS
    matches = [t for t in REPAIR_TARGETS if t.domain == name]
    if not matches:
        raise SystemExit(
            f"Unknown target {name!r}; expected one of "
            f"{sorted({'all'} | {t.domain for t in REPAIR_TARGETS})}."
        )
    return matches


def _run_dry_run(database_url: str, targets) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    report: dict = {
        "mode": "dry_run",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "access": "read_only_transaction_rolled_back",
        "targets": [],
    }
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            for target in targets:
                measurement = measure_repair_candidates(cur, target)
                plan = build_repair_plan(measurement)
                sql_text = generate_repair_sql(target, plan)
                report["targets"].append(
                    {
                        "domain": target.domain,
                        "table": target.table,
                        "measurement": measurement,
                        "planned_updates": len(plan["actions"]),
                        "generated_sql": sql_text,
                    }
                )
        conn.rollback()
    return report


def _run_execute(database_url: str, targets) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    report: dict = {
        "mode": "execute",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "targets": [],
    }
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            for target in targets:
                measurement = measure_repair_candidates(cur, target)
                plan = build_repair_plan(measurement)
                result = apply_repair_plan(cur, target, plan, execute=True)
                if result["rows_updated"] != result["planned"]:
                    conn.rollback()
                    result["status"] = "rolled_back_mismatch"
                    report["targets"].append(
                        {"domain": target.domain, "table": target.table, "result": result}
                    )
                    continue
                conn.commit()
                report["targets"].append(
                    {"domain": target.domain, "table": target.table, "result": result}
                )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default="all",
        help="one of: all, " + ", ".join(sorted({t.domain for t in REPAIR_TARGETS})),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="write the resolved candidates instead of only reporting them",
    )
    parser.add_argument(
        "--report",
        default=os.environ.get(
            "CALYX_TAXONOMY_ID_REPAIR_REPORT",
            "taxonomy-id-repair-report.json",
        ),
    )
    args = parser.parse_args()

    targets = _targets_for(args.target)
    database_url = os.environ.get("DATABASE_URL", "")

    if not args.execute:
        if not database_url:
            report = {
                "mode": "dry_run",
                "status": "no_database_url",
                "targets": [t.domain for t in targets],
                "note": "DATABASE_URL not set; nothing was read or written.",
            }
        else:
            report = _run_dry_run(database_url, targets)
    else:
        confirmation = os.environ.get("CALYX_TAXONOMY_ID_REPAIR_CONFIRMATION", "").strip()
        if confirmation != EXECUTION_CONFIRMATION:
            raise SystemExit(
                "Refusing to execute: CALYX_TAXONOMY_ID_REPAIR_CONFIRMATION must "
                f"equal {EXECUTION_CONFIRMATION!r}. This is the owner gate for a "
                "write to production taxonomy linkage; --execute alone is not enough."
            )
        if not database_url:
            raise SystemExit("DATABASE_URL is required to execute.")
        report = _run_execute(database_url, targets)

    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
