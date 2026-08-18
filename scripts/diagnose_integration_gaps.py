"""Read-only production diagnostics for DATA-INTEGRATION-REPAIR-001.

Answers four questions the AUDIT-MEASUREMENT-002 evidence raised but could not
settle, all of which are schema questions rather than judgement calls:

1. Which occurrence relation is canonical? 26 rows and ~580,612 rows both claim it.
2. The pollinator and mycorrhiza tables carry orchid_taxonomy_id values that
   resolve to nothing in oc_taxonomy.taxa. Which taxonomy relation do they
   actually belong to?
3. 695 habitat claims exist and 2 reach taxonomy. Where do the other 693 point?
4. Every elevation column found so far is empty. Does any relation in the
   database hold elevation values?

Strictly read-only: catalog reads, COUNTs, and joins, inside a read-only
transaction that is rolled back. Row *data* is never emitted -- only counts,
column names, and type names. Each probe runs inside a savepoint so a type
mismatch on one candidate cannot abort the whole diagnostic.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OUT_PATH = os.environ.get("DIAGNOSTIC_PATH", "integration-gap-diagnostic.json")

# Relations that might serve as the taxonomy identity anchor. Every id-bearing
# column below is tested against all of them, because "which taxonomy table do
# these ids belong to" is answerable by measurement rather than by assumption.
TAXONOMY_CANDIDATES = (
    ("oc_taxonomy.taxa", "taxon_id"),
    ("oc_taxonomy.taxa", "accepted_taxon_id"),
    ("oc_taxonomy.taxa", "source_record_id"),
    ("public.orchid_taxonomy", "id"),
    ("public.orchid_taxonomy", "taxon_id"),
    ("oc_graph.kg_nodes", "source_pk"),
    ("public.orchid_species", "id"),
    ("public.orchid_taxa", "id"),
)

# Foreign keys whose target is in question.
ORPHAN_KEYS = (
    ("oc_interactions.orchid_interaction_edges", "orchid_taxonomy_id"),
    ("oc_mycorrhiza.orchid_fungal_associations", "orchid_taxonomy_id"),
    ("public.oc_species_habitat_claims", "taxon_id"),
    ("public.oc_species_habitat_claims", "taxonomy_id"),
    ("public.orchid_occurrence", "taxon_id"),
    ("public.orchid_occurrence", "taxonomy_id"),
    ("public.orchid_occurrence", "orchid_taxonomy_id"),
    ("oc_atlas.occurrences", "taxon_id"),
    ("public.records", "taxon_id"),
    ("public.records", "taxonomy_id"),
    ("public.records", "orchid_taxonomy_id"),
    ("public.records", "accepted_taxon_id"),
    ("public.oc_occurrences", "taxon_id"),
    ("public.oc_occurrences", "taxonomy_id"),
    ("oc_stage.mx_occurrence_final_v3", "taxonomy_id"),
    ("oc_stage.mx_occurrence_final_v3", "taxon_id"),
)

# The first pass of this diagnostic only knew the relations already named in the
# metric candidate lists, and concluded public.orchid_occurrence was canonical on
# 580,612 rows. The corrected column scan then found public.records carrying
# 2,934,913 elevation values and public.oc_occurrences another 37,794, against
# 7 on public.orchid_occurrence. A candidate list can only settle a question
# among the relations it happens to name, so these are now probed too.
OCCURRENCE_CANDIDATES = (
    "oc_atlas.occurrences",
    "oc_views.occurrences_enriched",
    "public.orchid_occurrence",
    "public.orchid_occurrences",
    "public.occurrences",
    "public.records",
    "public.oc_occurrences",
    "public.v_orchid_records",
    "oc_stage.mx_occurrence_final_v3",
)


def q(cur, sql, params=()):
    """Run one probe inside a savepoint so a failure cannot poison the session."""
    cur.execute("SAVEPOINT probe")
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.execute("RELEASE SAVEPOINT probe")
        return rows, None
    except Exception as exc:  # noqa: BLE001 - the error IS the diagnostic
        cur.execute("ROLLBACK TO SAVEPOINT probe")
        cur.execute("RELEASE SAVEPOINT probe")
        return None, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"


def scalar(cur, sql, params=()):
    rows, err = q(cur, sql, params)
    if err or not rows:
        return None, err
    row = rows[0]
    return (next(iter(row.values())) if isinstance(row, dict) else row[0]), None


def relation_info(cur, name):
    rows, err = q(
        cur,
        """
        SELECT c.relkind::text AS relkind, c.reltuples::bigint AS reltuples
        FROM pg_class c WHERE c.oid = to_regclass(%s)
        """,
        (name,),
    )
    if err or not rows:
        return {"exists": False, "error": err}
    info = {"exists": True, "relkind": rows[0]["relkind"], "approximate_rows": rows[0]["reltuples"]}
    exact, err = scalar(cur, f"SELECT COUNT(*) FROM {name}")
    info["exact_rows"] = exact
    if err:
        info["count_error"] = err
    return info


def columns_with_types(cur, name):
    schema, _, table = name.partition(".")
    if not table:
        schema, table = "public", schema
    rows, err = q(
        cur,
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    if err or rows is None:
        return {}, err
    return {r["column_name"]: r["data_type"] for r in rows}, None


def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL is not set.")
        return 1

    out = {
        "contract": "OCU-INTEGRATION-GAP-DIAGNOSTIC-001",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "access": "read_only_transaction_rolled_back",
    }

    with psycopg.connect(DATABASE_URL, connect_timeout=20) as conn:
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET statement_timeout = '120s'")

            # --- 1. Occurrence relations -------------------------------
            occ = {}
            for name in OCCURRENCE_CANDIDATES:
                info = relation_info(cur, name)
                if info.get("exists"):
                    cols, _ = columns_with_types(cur, name)
                    info["columns"] = cols
                    if info.get("relkind") in {"v", "m"}:
                        d, _ = scalar(
                            cur, "SELECT pg_get_viewdef(to_regclass(%s), true)", (name,)
                        )
                        info["view_definition"] = (d or "")[:1200]
                occ[name] = info
            out["occurrence_candidates"] = occ

            # --- 2. Where do the orphan keys actually point? ------------
            resolution = {}
            for table, column in ORPHAN_KEYS:
                cols, _ = columns_with_types(cur, table)
                if column not in cols:
                    resolution[f"{table}.{column}"] = {"column_present": False}
                    continue
                entry = {
                    "column_present": True,
                    "data_type": cols[column],
                    "resolves_against": {},
                }
                entry["non_null"], _ = scalar(
                    cur, f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL"
                )
                entry["distinct_non_null"], _ = scalar(
                    cur, f"SELECT COUNT(DISTINCT {column}) FROM {table} WHERE {column} IS NOT NULL"
                )
                for tax_table, tax_col in TAXONOMY_CANDIDATES:
                    tax_cols, _ = columns_with_types(cur, tax_table)
                    if tax_col not in tax_cols:
                        continue
                    # Cast both sides to text so a uuid/bigint/text mismatch is a
                    # measurement rather than an error. This asks "do these values
                    # exist over there", which is the actual question.
                    matched, err = scalar(
                        cur,
                        f"""
                        SELECT COUNT(*) FROM {table} o
                        JOIN {tax_table} t ON t.{tax_col}::text = o.{column}::text
                        WHERE o.{column} IS NOT NULL
                        """,
                    )
                    entry["resolves_against"][f"{tax_table}.{tax_col}"] = (
                        {"matched": matched} if not err else {"error": err}
                    )
                resolution[f"{table}.{column}"] = entry
            out["orphan_key_resolution"] = resolution

            # --- 3. Habitat claims -------------------------------------
            hab = relation_info(cur, "public.oc_species_habitat_claims")
            if hab.get("exists"):
                cols, _ = columns_with_types(cur, "public.oc_species_habitat_claims")
                hab["columns"] = cols
                hab["null_counts"] = {}
                for c in cols:
                    if any(k in c for k in ("taxon", "species", "name", "scientific")):
                        n, _ = scalar(
                            cur,
                            f"SELECT COUNT(*) FROM public.oc_species_habitat_claims WHERE {c} IS NOT NULL",
                        )
                        hab["null_counts"][c] = n
            out["habitat_claims"] = hab

            # --- 4. Any elevation values anywhere ----------------------
            # The pattern must be a bound parameter. Inlined, psycopg reads the
            # %e of "%elevation%" as a placeholder and refuses the statement --
            # which is how the first run reported that the database held no
            # elevation columns at all, while public.orchid_occurrence carried
            # six. A scan that could not run must never read as a scan that
            # found nothing.
            rows, err = q(
                cur,
                """
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE (column_name ILIKE %s OR column_name ILIKE %s
                       OR column_name ILIKE %s OR column_name ILIKE %s)
                  AND table_schema NOT IN ('pg_catalog','information_schema')
                ORDER BY table_schema, table_name, column_name
                """,
                ("%elevation%", "%habitat%", "%climate%", "%altitude%"),
            )
            elevation = []
            for r in rows or []:
                fq = f"{r['table_schema']}.{r['table_name']}"
                populated, e = scalar(
                    cur, f"SELECT COUNT(*) FROM {fq} WHERE {r['column_name']} IS NOT NULL"
                )
                elevation.append(
                    {
                        "relation": fq,
                        "column": r["column_name"],
                        "data_type": r["data_type"],
                        "populated_rows": populated,
                        "error": e,
                    }
                )
            out["elevation_columns"] = elevation
            out["elevation_scan_error"] = err

            # --- 5. Do the adapter-declared relations exist at all? -----
            declared = {}
            for name in (
                "oc_env.taxon_elevation_profiles",
                "oc_habitat.taxon_habitats",
                "oc_env_intel.species_environment_profile",
                "oc_interactions.orchid_interaction_edges",
                "oc_mycorrhiza.orchid_fungal_associations",
                "oc_conservation.conservation_records",
                "oc_graph.taxon_literature_edges",
                "oc_taxonomy.taxa",
                "public.orchid_taxonomy",
            ):
                declared[name] = relation_info(cur, name)
            out["declared_relations"] = declared

        conn.rollback()

    with open(OUT_PATH, "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    print("=== occurrence candidates ===")
    for n, i in out["occurrence_candidates"].items():
        if i.get("exists"):
            print(f"  {n:42s} kind={i.get('relkind')} exact={i.get('exact_rows')}")
        else:
            print(f"  {n:42s} ABSENT")
    print()
    print("=== orphan key resolution ===")
    for k, v in out["orphan_key_resolution"].items():
        if not v.get("column_present"):
            print(f"  {k:60s} column absent")
            continue
        hits = {t: r.get("matched") for t, r in v["resolves_against"].items() if r.get("matched")}
        print(f"  {k:60s} type={v['data_type']} non_null={v['non_null']} -> {hits or 'NOTHING MATCHES'}")
    print()
    print("=== elevation columns ===")
    for e in out["elevation_columns"]:
        if e["populated_rows"]:
            print(f"  {e['relation']}.{e['column']:28s} populated={e['populated_rows']:,}")
    empty = [e for e in out["elevation_columns"] if not e["populated_rows"]]
    print(f"  ({len(empty)} further matching column(s) exist but hold no values)")
    print()
    print("=== declared relations ===")
    for n, i in out["declared_relations"].items():
        print(f"  {n:46s} exists={i.get('exists')} rows={i.get('exact_rows')}")
    print()
    print(f"written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
