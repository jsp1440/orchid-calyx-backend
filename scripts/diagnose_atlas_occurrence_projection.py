"""Read-only diagnostic for the Atlas occurrence-projection decision.

Answers, by measurement, what the proposed projection
(docs/atlas-explorer/20261011_atlas_public_occurrences_v1.sql) can honestly
serve from the current database:

1. Which candidate occurrence relations exist, with their columns and sizes.
2. For public.orchid_occurrence: usable-coordinate coverage, taxonomy linkage
   into public.orchid_taxonomy, and coordinate precision (as counts only).
3. Which Darwin Core terms the raw payloads actually carry (licence, dataset,
   basis of record, coordinate uncertainty, ...), counted over linked rows.
4. Taxonomic scope: the families linked rows state, and the genera whose
   records state a family other than Orchidaceae (e.g. Hypoxis).
5. Whether public.orchid_taxonomy has a family column and what it holds.
6. Conservation-assessment coverage and the indexes on the source table.

Strictly read-only: catalog reads and aggregates inside a read-only
transaction that is rolled back. It never emits a coordinate, locality,
occurrence identifier or payload value; only counts, column names, family
names and genus names.

Usage: DATABASE_URL=... python scripts/diagnose_atlas_occurrence_projection.py
Writes ATLAS_PROJECTION_DIAGNOSTIC_PATH (default
atlas-occurrence-projection-diagnostic.json) and prints a short summary.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

SOURCE = "public.orchid_occurrence"
TAXONOMY = "public.orchid_taxonomy"
CANDIDATES = (
    SOURCE,
    "oc_atlas.occurrences",
    "oc_atlas.species_atlas_v1",
    "oc_atlas.gbif_source_inventory_v1",
    "oc_atlas.public_occurrences_v1",
    TAXONOMY,
    "oc_taxonomy.taxa",
    "oc_conservation.conservation_records",
)
DWC_TERMS = (
    "family",
    "license",
    "datasetName",
    "datasetKey",
    "basisOfRecord",
    "coordinateUncertaintyInMeters",
    "institutionCode",
    "rightsHolder",
    "countryCode",
    "occurrenceStatus",
    "establishmentMeans",
)
TARGET = "Orchidaceae"

LINKED = f"""
    FROM {SOURCE} o
    JOIN {TAXONOMY} t ON t.id = o.taxonomy_id
    WHERE o.decimal_latitude BETWEEN -90 AND 90
      AND o.decimal_longitude BETWEEN -180 AND 180
      AND NOT (o.decimal_latitude = 0 AND o.decimal_longitude = 0)
"""


def q(cur: Any, sql: str, params: tuple = ()) -> tuple[list[dict] | None, str | None]:
    cur.execute("SAVEPOINT p")
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.execute("RELEASE SAVEPOINT p")
        return [dict(r) for r in rows], None
    except Exception as exc:  # noqa: BLE001 - the error is part of the answer
        cur.execute("ROLLBACK TO SAVEPOINT p")
        cur.execute("RELEASE SAVEPOINT p")
        return None, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"


def scalar(cur: Any, sql: str, params: tuple = ()) -> tuple[Any, str | None]:
    rows, err = q(cur, sql, params)
    if err or not rows:
        return None, err
    return next(iter(rows[0].values())), None


def _columns(cur: Any, relation: str) -> dict[str, str]:
    schema, name = relation.split(".")
    rows, _ = q(
        cur,
        """
        SELECT a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS data_type
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, name),
    )
    return {r["column_name"]: r["data_type"] for r in rows or []}


def diagnose(cur: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "contract": "ATLAS-EXPLORER-001-PROJECTION-DIAGNOSTIC",
        "captured_at": datetime.now(UTC).isoformat(),
        "access": "read_only_transaction_rolled_back",
        "emits": "counts, column names, family names and genus names only",
    }

    candidates: dict[str, Any] = {}
    for relation in CANDIDATES:
        kind, err = scalar(
            cur,
            "SELECT relkind::text FROM pg_class WHERE oid = to_regclass(%s)",
            (relation,),
        )
        if kind is None:
            candidates[relation] = {"exists": False, "error": err}
            continue
        rows, count_err = scalar(cur, f"SELECT count(*) FROM {relation}")
        candidates[relation] = {
            "exists": True,
            "relkind": kind,
            "exact_rows": rows,
            "count_error": count_err,
            "columns": _columns(cur, relation),
        }
    out["candidates"] = candidates
    if not candidates.get(SOURCE, {}).get("exists") or not candidates.get(
        TAXONOMY, {}
    ).get("exists"):
        out["verdict"] = {
            "projection_possible": False,
            "reason": f"{SOURCE} or {TAXONOMY} is missing",
        }
        return out

    coverage, err = q(
        cur,
        f"""
        SELECT count(*) AS rows,
               count(*) FILTER (WHERE o.decimal_latitude IS NOT NULL AND o.decimal_longitude IS NOT NULL) AS with_coordinates,
               count(*) FILTER (WHERE o.decimal_latitude = 0 AND o.decimal_longitude = 0) AS null_island,
               count(*) FILTER (WHERE abs(o.decimal_latitude) > 90 OR abs(o.decimal_longitude) > 180) AS out_of_range,
               count(*) FILTER (WHERE o.taxonomy_id IS NOT NULL) AS with_taxonomy_id,
               count(t.id) AS linked_to_backbone,
               count(t.id) FILTER (
                   WHERE o.decimal_latitude BETWEEN -90 AND 90
                     AND o.decimal_longitude BETWEEN -180 AND 180
                     AND NOT (o.decimal_latitude = 0 AND o.decimal_longitude = 0)) AS projectable,
               count(t.id) FILTER (
                   WHERE round(o.decimal_latitude::numeric, 2) = o.decimal_latitude::numeric
                     AND round(o.decimal_longitude::numeric, 2) = o.decimal_longitude::numeric) AS linked_at_most_2dp
        FROM {SOURCE} o
        LEFT JOIN {TAXONOMY} t ON t.id = o.taxonomy_id
        """,
    )
    out["coverage"] = (coverage or [{}])[0]
    out["coverage_error"] = err

    terms: dict[str, Any] = {}
    for term in DWC_TERMS:
        n, err = scalar(
            cur,
            f"SELECT count(*) {LINKED} AND NULLIF(btrim(o.raw_payload ->> %s), '') IS NOT NULL",
            (term,),
        )
        terms[term] = {"rows_with_value": n, "error": err}
    out["raw_payload_terms_on_projectable_rows"] = terms

    families, err = q(
        cur,
        f"""
        SELECT COALESCE(NULLIF(btrim(o.raw_payload ->> 'family'), ''), '(not stated)') AS family, count(*) AS n
        {LINKED}
        GROUP BY 1 ORDER BY 2 DESC LIMIT 25
        """,
    )
    out["stated_families"] = families
    out["stated_families_error"] = err
    out_of_scope, err = q(
        cur,
        f"""
        SELECT COALESCE(t.genus, split_part(o.canonical_name_clean, ' ', 1)) AS genus,
               btrim(o.raw_payload ->> 'family') AS stated_family, count(*) AS n
        {LINKED}
          AND NULLIF(btrim(o.raw_payload ->> 'family'), '') IS NOT NULL
          AND lower(btrim(o.raw_payload ->> 'family')) <> lower(%s)
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 50
        """,
        (TARGET,),
    )
    out["genera_stating_non_orchid_family"] = out_of_scope
    out["genera_stating_non_orchid_family_error"] = err

    backbone_cols = candidates[TAXONOMY]["columns"]
    if "family" in backbone_cols:
        rows, err = q(
            cur,
            f"SELECT COALESCE(family, '(null)') AS family, count(*) AS n FROM {TAXONOMY} GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
        )
        out["backbone_family"] = {"column_present": True, "values": rows, "error": err}
    else:
        out["backbone_family"] = {"column_present": False}

    out["conservation_records"] = candidates.get(
        "oc_conservation.conservation_records", {}
    ).get("exact_rows")
    indexes, err = q(
        cur,
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'orchid_occurrence'",
    )
    out["source_indexes"] = indexes
    out["source_indexes_error"] = err

    stated = {r["family"]: r["n"] for r in families or []}
    projectable = out["coverage"].get("projectable") or 0
    out["verdict"] = {
        "projection_possible": projectable > 0,
        "projectable_rows": projectable,
        "rows_excluded_as_non_orchid": sum(r["n"] for r in out_of_scope or []),
        "rows_relying_on_backbone_for_family": stated.get("(not stated)", 0),
        "licence_stated_rows": terms["license"]["rows_with_value"],
        "uncertainty_stated_rows": terms["coordinateUncertaintyInMeters"][
            "rows_with_value"
        ],
        "assessment_source_rows": out["conservation_records"],
    }
    return out


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set.")
        return 1
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url, connect_timeout=20) as conn:
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET statement_timeout = '240s'")
            report = diagnose(cur)
        conn.rollback()

    path = os.environ.get(
        "ATLAS_PROJECTION_DIAGNOSTIC_PATH",
        "atlas-occurrence-projection-diagnostic.json",
    )
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    print(json.dumps(report["verdict"], indent=2, default=str))
    print(f"full report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
