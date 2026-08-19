"""Read-only diagnostic for the occurrence-semantics decision.

Answers, with measurement rather than inference:

1. The COMPLETE set of record_type values in public.records, not a top-N slice.
   A classification that silently ignores a long tail is not a classification.
2. How the explicitly-typed occurrence rows in public.records relate to the rows
   in public.orchid_occurrence -- overlap, and by which identifier.
3. Elevation coverage per record_type, so elevation can be measured over
   genuine occurrence evidence instead of over whatever happens to carry a
   number.

Strictly read-only: catalog reads, COUNTs and joins inside a read-only
transaction that is rolled back. No row data is emitted; counts, column names
and record_type labels only.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OUT_PATH = os.environ.get(
    "OCCURRENCE_SEMANTICS_PATH", "occurrence-semantics-diagnostic.json"
)


def q(cur, sql, params=()):
    cur.execute("SAVEPOINT p")
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.execute("RELEASE SAVEPOINT p")
        return rows, None
    except Exception as exc:  # noqa: BLE001 - the error is part of the answer
        cur.execute("ROLLBACK TO SAVEPOINT p")
        cur.execute("RELEASE SAVEPOINT p")
        return None, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"


def scalar(cur, sql, params=()):
    rows, err = q(cur, sql, params)
    if err or not rows:
        return None, err
    r = rows[0]
    return (next(iter(r.values())) if isinstance(r, dict) else r[0]), None


def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL is not set.")
        return 1

    out = {
        "contract": "OCU-OCCURRENCE-SEMANTICS-DIAGNOSTIC-001",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "access": "read_only_transaction_rolled_back",
    }

    with psycopg.connect(DATABASE_URL, connect_timeout=20) as conn:
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET statement_timeout = '240s'")

            # --- 1. EVERY record_type, with elevation and coordinate coverage
            rows, err = q(
                cur,
                """
                SELECT COALESCE(record_type::text, '(null)') AS record_type,
                       COUNT(*) AS rows,
                       COUNT(*) FILTER (WHERE elevation_m IS NOT NULL) AS with_elevation,
                       COUNT(*) FILTER (WHERE latitude IS NOT NULL
                                          AND longitude IS NOT NULL) AS with_coordinates,
                       COUNT(*) FILTER (WHERE event_date IS NOT NULL) AS with_event_date,
                       COUNT(*) FILTER (WHERE gbif_occurrence_key IS NOT NULL) AS with_gbif_key,
                       COUNT(*) FILTER (WHERE scientific_binomial IS NOT NULL) AS with_binomial
                FROM public.records
                GROUP BY 1
                ORDER BY 2 DESC
                """,
            )
            out["record_types"] = [dict(r) for r in (rows or [])]
            out["record_types_error"] = err
            out["record_type_count"] = len(rows or [])

            # --- 2. How do the two corpora relate? ---------------------
            rel = {}
            rel["orchid_occurrence_rows"], _ = scalar(
                cur, "SELECT COUNT(*) FROM public.orchid_occurrence"
            )
            rel["records_rows"], _ = scalar(cur, "SELECT COUNT(*) FROM public.records")

            # orchid_occurrence carries source_table/source_record_id; if it was
            # derived FROM records, that is where the trail will be.
            rows, err = q(
                cur,
                """
                SELECT COALESCE(source_table::text, '(null)') AS source_table,
                       COUNT(*) AS rows
                FROM public.orchid_occurrence
                GROUP BY 1 ORDER BY 2 DESC LIMIT 30
                """,
            )
            rel["orchid_occurrence_source_tables"] = [dict(r) for r in (rows or [])]
            rel["orchid_occurrence_source_tables_error"] = err

            # Overlap on the GBIF key, which both sides carry under different names.
            rel["overlap_on_gbif_key"], rel["overlap_on_gbif_key_error"] = scalar(
                cur,
                """
                SELECT COUNT(*)
                FROM public.orchid_occurrence o
                JOIN public.records r
                  ON r.gbif_occurrence_key::text = o.canonical_gbif_occurrence_key::text
                WHERE o.canonical_gbif_occurrence_key IS NOT NULL
                """,
            )
            rel["orchid_occurrence_with_gbif_key"], _ = scalar(
                cur,
                "SELECT COUNT(*) FROM public.orchid_occurrence "
                "WHERE canonical_gbif_occurrence_key IS NOT NULL",
            )
            rel["records_occurrence_typed_with_gbif_key"], _ = scalar(
                cur,
                "SELECT COUNT(*) FROM public.records "
                "WHERE record_type = 'occurrence' AND gbif_occurrence_key IS NOT NULL",
            )
            # And on source_record_id, the other identifier both sides carry.
            rel["overlap_on_source_record_id"], rel["overlap_on_source_record_id_error"] = scalar(
                cur,
                """
                SELECT COUNT(*)
                FROM public.orchid_occurrence o
                JOIN public.records r
                  ON r.source_record_id::text = o.source_record_id::text
                WHERE o.source_record_id IS NOT NULL
                """,
            )
            out["corpus_relationship"] = rel

            # --- 3. Taxonomy reachability per record_type --------------
            rows, err = q(
                cur,
                """
                SELECT COALESCE(r.record_type::text, '(null)') AS record_type,
                       COUNT(*) FILTER (WHERE t.taxon_id IS NOT NULL) AS reaches_taxa,
                       COUNT(*) FILTER (WHERE r.elevation_m IS NOT NULL
                                          AND t.taxon_id IS NOT NULL) AS elevation_and_taxon
                FROM public.records r
                LEFT JOIN oc_taxonomy.taxa t
                  ON lower(t.canonical_name) = lower(r.scientific_binomial)
                GROUP BY 1 ORDER BY 2 DESC NULLS LAST
                """,
            )
            out["taxonomy_reach_by_type"] = [dict(r) for r in (rows or [])]
            out["taxonomy_reach_by_type_error"] = err

    with open(OUT_PATH, "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    print(f"=== record_type values: {out['record_type_count']} distinct ===")
    print(f"{'record_type':38s} {'rows':>10s} {'elev':>9s} {'coords':>9s} {'date':>9s} {'gbif':>9s}")
    for r in out["record_types"]:
        print(
            f"{str(r['record_type'])[:38]:38s} {r['rows']:>10,} "
            f"{r['with_elevation']:>9,} {r['with_coordinates']:>9,} "
            f"{r['with_event_date']:>9,} {r['with_gbif_key']:>9,}"
        )
    print()
    print("=== corpus relationship ===")
    for k, v in out["corpus_relationship"].items():
        if k.endswith("_error") and not v:
            continue
        if k == "orchid_occurrence_source_tables":
            print("  orchid_occurrence.source_table:")
            for e in v:
                print(f"      {str(e['source_table'])[:44]:46s} {e['rows']:,}")
            continue
        print(f"  {k:44s} {v}")
    print()
    print("=== taxonomy reach by record_type (name join) ===")
    for r in out["taxonomy_reach_by_type"][:25]:
        print(
            f"  {str(r['record_type'])[:38]:38s} "
            f"reaches_taxa={r['reaches_taxa']:<12,} elev+taxon={r['elevation_and_taxon']:,}"
        )
    print()
    print(f"written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
