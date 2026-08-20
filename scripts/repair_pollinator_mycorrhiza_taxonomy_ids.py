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

Both modes emit two review artifacts per target: a provenance mapping CSV
accounting for every candidate row (written, queued for a human, or resolving
to nothing) and the generated idempotent repair SQL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.readiness.taxonomy_id_repair import (  # noqa: E402
    REPAIR_PACKAGE,
    REPAIR_TARGETS,
    RESOLUTION_POLICY,
    apply_repair_plan,
    build_provenance_mapping,
    build_repair_plan,
    generate_repair_sql,
    mapping_to_csv,
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


def _artifact_path(base: str, domain: str) -> str:
    root, ext = os.path.splitext(base)
    return f"{root}.{domain}{ext}"


def write_artifacts(target, measurement, plan, sql_text, *, mapping_out, sql_out) -> dict:
    """Write the provenance mapping and the reviewable SQL for one target.

    These are the two review handoffs: the mapping accounts for every
    candidate row (written, queued for a human, or resolving to nothing), and
    the SQL is the exact idempotent text a reviewer would run. Writing them is
    a local file operation and touches no database.
    """
    mapping = build_provenance_mapping(target, measurement)
    mapping_path = _artifact_path(mapping_out, target.domain)
    sql_path = _artifact_path(sql_out, target.domain)

    with open(mapping_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(mapping_to_csv(mapping))
    with open(sql_path, "w", encoding="utf-8") as fh:
        fh.write(sql_text)

    return {
        "mapping_csv": mapping_path,
        "mapping_rows": len(mapping),
        "repair_sql": sql_path,
        "planned_updates": len(plan["actions"]),
    }


def _run_dry_run(database_url: str, targets, *, mapping_out: str, sql_out: str) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    report: dict = {
        "mode": "dry_run",
        "repair_package": REPAIR_PACKAGE,
        "resolution_policy": RESOLUTION_POLICY,
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
                        "artifacts": write_artifacts(
                            target,
                            measurement,
                            plan,
                            sql_text,
                            mapping_out=mapping_out,
                            sql_out=sql_out,
                        ),
                    }
                )
        conn.rollback()
    return report


def _run_execute(database_url: str, targets, *, mapping_out: str, sql_out: str) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    report: dict = {
        "mode": "execute",
        "repair_package": REPAIR_PACKAGE,
        "resolution_policy": RESOLUTION_POLICY,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "targets": [],
    }
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            for target in targets:
                measurement = measure_repair_candidates(cur, target)
                plan = build_repair_plan(measurement)
                # The mapping and SQL are written before the transaction is
                # committed, so the provenance of a write always exists on
                # disk even if the write itself is rolled back or interrupted.
                artifacts = write_artifacts(
                    target,
                    measurement,
                    plan,
                    generate_repair_sql(target, plan),
                    mapping_out=mapping_out,
                    sql_out=sql_out,
                )
                result = apply_repair_plan(cur, target, plan, execute=True)
                if result["rows_updated"] != result["planned"]:
                    conn.rollback()
                    result["status"] = "rolled_back_mismatch"
                    report["targets"].append(
                        {
                            "domain": target.domain,
                            "table": target.table,
                            "result": result,
                            "artifacts": artifacts,
                        }
                    )
                    continue
                conn.commit()
                report["targets"].append(
                    {
                        "domain": target.domain,
                        "table": target.table,
                        "result": result,
                        "artifacts": artifacts,
                    }
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
    parser.add_argument(
        "--mapping-out",
        default=os.environ.get(
            "CALYX_TAXONOMY_ID_REPAIR_MAPPING",
            "taxonomy-id-repair-mapping.csv",
        ),
        help="provenance mapping CSV; one file per target, suffixed with the domain",
    )
    parser.add_argument(
        "--sql-out",
        default=os.environ.get(
            "CALYX_TAXONOMY_ID_REPAIR_SQL",
            "taxonomy-id-repair.sql",
        ),
        help="generated idempotent repair SQL; one file per target, suffixed with the domain",
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
            report = _run_dry_run(
                database_url, targets, mapping_out=args.mapping_out, sql_out=args.sql_out
            )
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
        report = _run_execute(
            database_url, targets, mapping_out=args.mapping_out, sql_out=args.sql_out
        )

    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
