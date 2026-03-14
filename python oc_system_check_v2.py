# oc_sentinel.py
#!/usr/bin/env python3

import os
import json
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

REPORT_JSON = "oc_sentinel_report.json"
REPORT_TXT = "oc_sentinel_report.txt"

CANDIDATE_GROUPS = {
    "occurrences": [
        "oc_occurrences",
        "oc_occurrence_records",
        "occurrences",
        "orchid_occurrences",
        "public.oc_occurrences",
        "public.oc_occurrence_records",
    ],
    "images": [
        "oc_images",
        "oc_media",
        "orchid_images",
        "media",
        "public.oc_images",
        "public.oc_media",
    ],
    "taxa": [
        "oc_taxa",
        "taxa",
        "orchid_taxa",
        "public.oc_taxa",
        "public.taxa",
    ],
    "traits": [
        "oc_traits",
        "traits",
        "orchid_traits",
        "public.oc_traits",
    ],
    "atlas": [
        "oc_atlas_cells",
        "orchid_atlas_layer",
        "orchid_hotspot_grid",
        "public.oc_atlas_cells",
        "public.orchid_atlas_layer",
        "public.orchid_hotspot_grid",
    ],
    "harvesters": [
        "oc_harvesters",
        "harvesters",
        "public.oc_harvesters",
    ],
    "harvester_runs": [
        "oc_harvester_runs",
        "harvester_runs",
        "public.oc_harvester_runs",
    ],
    "record_taxon_map": [
        "record_taxon_map",
        "oc_record_taxon_map",
        "public.record_taxon_map",
        "public.oc_record_taxon_map",
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_print(*args: Any) -> None:
    print(*args, flush=True)


def connect() -> psycopg2.extensions.connection:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)


def query_all(
    conn: psycopg2.extensions.connection,
    sql: str,
    params: Optional[Tuple[Any, ...]] = None,
) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        try:
            rows = cur.fetchall()
        except psycopg2.ProgrammingError:
            rows = []
    return [dict(r) for r in rows]


def query_one_value(
    conn: psycopg2.extensions.connection,
    sql: str,
    params: Optional[Tuple[Any, ...]] = None,
) -> Any:
    rows = query_all(conn, sql, params)
    if not rows:
        return None
    first = rows[0]
    if not first:
        return None
    return next(iter(first.values()))


def table_exists(conn: psycopg2.extensions.connection,
                 table_name: str) -> bool:
    if "." in table_name:
        schema, table = table_name.split(".", 1)
    else:
        schema, table = "public", table_name

    sql = """
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_name = %s
    ) AS exists_flag
    """
    return bool(query_one_value(conn, sql, (schema, table)))


def list_tables(conn: psycopg2.extensions.connection) -> List[Dict[str, Any]]:
    sql = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name
    """
    return query_all(conn, sql)


def list_columns(conn: psycopg2.extensions.connection,
                 full_table_name: str) -> List[str]:
    if "." in full_table_name:
        schema, table = full_table_name.split(".", 1)
    else:
        schema, table = "public", full_table_name

    sql = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = %s
      AND table_name = %s
    ORDER BY ordinal_position
    """
    rows = query_all(conn, sql, (schema, table))
    return [r["column_name"] for r in rows]


def discover_table(
    conn: psycopg2.extensions.connection,
    candidates: List[str],
    required_columns: Optional[List[str]] = None,
) -> Optional[str]:
    required_columns = required_columns or []
    for candidate in candidates:
        if table_exists(conn, candidate):
            cols = set(list_columns(conn, candidate))
            if all(c in cols for c in required_columns):
                return candidate
    for candidate in candidates:
        if table_exists(conn, candidate):
            return candidate
    return None


def find_column(columns: List[str], preferred: List[str]) -> Optional[str]:
    colset = set(columns)
    for p in preferred:
        if p in colset:
            return p
    return None


def count_rows(conn: psycopg2.extensions.connection,
               table_name: str) -> Optional[int]:
    try:
        return int(
            query_one_value(conn, f"SELECT COUNT(*) AS c FROM {table_name}"))
    except Exception:
        conn.rollback()
        return None


def summarize_table(
    conn: psycopg2.extensions.connection,
    table_name: Optional[str],
) -> Dict[str, Any]:
    if not table_name:
        return {"table": None, "exists": False}
    try:
        columns = list_columns(conn, table_name)
        rows = count_rows(conn, table_name)
        return {
            "table": table_name,
            "exists": True,
            "row_count": rows,
            "columns": columns,
        }
    except Exception as e:
        conn.rollback()
        return {
            "table": table_name,
            "exists": True,
            "error": str(e),
        }


def section_wrapper(report: Dict[str, Any], name: str, fn) -> None:
    try:
        report["sections"][name] = fn()
    except Exception as e:
        report["sections"][name] = {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def build_schema_inventory(
        conn: psycopg2.extensions.connection) -> Dict[str, Any]:
    tables = list_tables(conn)
    return {
        "status": "ok",
        "table_count": len(tables),
        "tables": tables,
    }


def build_core_discovery(
        conn: psycopg2.extensions.connection) -> Dict[str, Any]:
    discovered = {
        "occurrences":
        discover_table(conn, CANDIDATE_GROUPS["occurrences"]),
        "images":
        discover_table(conn, CANDIDATE_GROUPS["images"]),
        "taxa":
        discover_table(conn, CANDIDATE_GROUPS["taxa"]),
        "traits":
        discover_table(conn, CANDIDATE_GROUPS["traits"]),
        "atlas":
        discover_table(conn, CANDIDATE_GROUPS["atlas"]),
        "harvesters":
        discover_table(conn, CANDIDATE_GROUPS["harvesters"]),
        "harvester_runs":
        discover_table(conn, CANDIDATE_GROUPS["harvester_runs"]),
        "record_taxon_map":
        discover_table(conn, CANDIDATE_GROUPS["record_taxon_map"]),
    }
    summaries = {k: summarize_table(conn, v) for k, v in discovered.items()}
    return {
        "status": "ok",
        "discovered": discovered,
        "summaries": summaries,
    }


def build_occurrence_audit(
    conn: psycopg2.extensions.connection,
    core: Dict[str, Any],
) -> Dict[str, Any]:
    table_name = core["discovered"].get("occurrences")
    if not table_name:
        return {"status": "missing", "message": "No occurrence table found"}

    columns = list_columns(conn, table_name)
    species_col = find_column(columns,
                              ["species", "species_name", "canonical_species"])
    genus_col = find_column(columns, ["genus", "genus_name"])
    lat_col = find_column(columns, ["lat", "latitude", "decimal_latitude"])
    lon_col = find_column(columns, ["lon", "longitude", "decimal_longitude"])
    elev_col = find_column(columns,
                           ["elevation_m", "elevation", "elevation_in_meters"])
    created_col = find_column(
        columns, ["created_at", "ingested_at", "updated_at", "loaded_at"])

    out: Dict[str, Any] = {
        "status": "ok",
        "table": table_name,
        "columns_found": {
            "species": species_col,
            "genus": genus_col,
            "lat": lat_col,
            "lon": lon_col,
            "elevation": elev_col,
            "timestamp": created_col,
        },
        "totals": {},
    }

    out["totals"]["row_count"] = count_rows(conn, table_name)

    if species_col:
        sql = f"SELECT COUNT(DISTINCT {species_col}) AS c FROM {table_name} WHERE {species_col} IS NOT NULL"
        out["totals"]["distinct_species"] = query_one_value(conn, sql)

    if genus_col:
        sql = f"SELECT COUNT(DISTINCT {genus_col}) AS c FROM {table_name} WHERE {genus_col} IS NOT NULL"
        out["totals"]["distinct_genera"] = query_one_value(conn, sql)

    if lat_col and lon_col:
        sql = f"""
        SELECT COUNT(*) AS c
        FROM {table_name}
        WHERE {lat_col} IS NOT NULL
          AND {lon_col} IS NOT NULL
        """
        out["totals"]["rows_with_coordinates"] = query_one_value(conn, sql)

    if elev_col:
        sql = f"""
        SELECT
            COUNT(*) FILTER (WHERE {elev_col} IS NOT NULL) AS with_elevation,
            COUNT(*) FILTER (WHERE {elev_col} IS NULL) AS missing_elevation,
            MIN({elev_col}) AS min_elevation,
            MAX({elev_col}) AS max_elevation
        FROM {table_name}
        """
        rows = query_all(conn, sql)
        out["elevation"] = rows[0] if rows else {}

    if created_col:
        sql = f"""
        SELECT MIN({created_col}) AS earliest_record,
               MAX({created_col}) AS latest_record
        FROM {table_name}
        """
        rows = query_all(conn, sql)
        out["freshness"] = rows[0] if rows else {}

    return out


def build_image_audit(
    conn: psycopg2.extensions.connection,
    core: Dict[str, Any],
) -> Dict[str, Any]:
    table_name = core["discovered"].get("images")
    if not table_name:
        return {"status": "missing", "message": "No image/media table found"}

    columns = list_columns(conn, table_name)
    taxon_col = find_column(columns,
                            ["taxon_id", "taxa_id", "accepted_taxon_id"])
    source_col = find_column(columns, ["source", "provider", "dataset_source"])
    url_col = find_column(columns,
                          ["url", "image_url", "media_url", "access_uri"])
    file_col = find_column(
        columns, ["file_path", "storage_path", "local_path", "object_path"])
    license_col = find_column(columns, ["license", "license_url"])

    out: Dict[str, Any] = {
        "status": "ok",
        "table": table_name,
        "columns_found": {
            "taxon": taxon_col,
            "source": source_col,
            "url": url_col,
            "file_path": file_col,
            "license": license_col,
        },
        "totals": {
            "row_count": count_rows(conn, table_name),
        },
    }

    if taxon_col:
        sql = f"SELECT COUNT(*) AS c FROM {table_name} WHERE {taxon_col} IS NOT NULL"
        out["totals"]["linked_to_taxa"] = query_one_value(conn, sql)

        sql = f"SELECT COUNT(*) AS c FROM {table_name} WHERE {taxon_col} IS NULL"
        out["totals"]["missing_taxonomy_link"] = query_one_value(conn, sql)

    if source_col:
        sql = f"""
        SELECT {source_col} AS source, COUNT(*) AS count
        FROM {table_name}
        GROUP BY {source_col}
        ORDER BY count DESC
        LIMIT 25
        """
        out["by_source"] = query_all(conn, sql)

    if url_col:
        sql = f"""
        SELECT COUNT(*) AS c
        FROM {table_name}
        WHERE {url_col} IS NULL
        """
        out["totals"]["missing_url"] = query_one_value(conn, sql)

        sql = f"""
        SELECT {url_col} AS url, COUNT(*) AS dup_count
        FROM {table_name}
        WHERE {url_col} IS NOT NULL
        GROUP BY {url_col}
        HAVING COUNT(*) > 1
        ORDER BY dup_count DESC
        LIMIT 20
        """
        out["duplicate_urls"] = query_all(conn, sql)

    if file_col:
        sql = f"""
        SELECT COUNT(*) AS c
        FROM {table_name}
        WHERE {file_col} IS NULL
        """
        out["totals"]["missing_file_path"] = query_one_value(conn, sql)

    return out


def build_taxonomy_audit(
    conn: psycopg2.extensions.connection,
    core: Dict[str, Any],
) -> Dict[str, Any]:
    table_name = core["discovered"].get("taxa")
    if not table_name:
        return {"status": "missing", "message": "No taxa table found"}

    columns = list_columns(conn, table_name)
    rank_col = find_column(columns, ["rank", "taxon_rank"])
    canonical_col = find_column(
        columns, ["canonical", "canonical_name", "scientific_name"])
    accepted_col = find_column(
        columns, ["accepted_id", "accepted_taxon_id", "parent_accepted_id"])

    out: Dict[str, Any] = {
        "status": "ok",
        "table": table_name,
        "columns_found": {
            "rank": rank_col,
            "canonical": canonical_col,
            "accepted": accepted_col,
        },
        "totals": {
            "row_count": count_rows(conn, table_name),
        },
    }

    if rank_col:
        sql = f"""
        SELECT {rank_col} AS rank, COUNT(*) AS count
        FROM {table_name}
        GROUP BY {rank_col}
        ORDER BY count DESC
        """
        out["by_rank"] = query_all(conn, sql)

    if canonical_col:
        sql = f"""
        SELECT COUNT(*) AS c
        FROM {table_name}
        WHERE {canonical_col} IS NULL
           OR TRIM(CAST({canonical_col} AS text)) = ''
        """
        out["totals"]["blank_canonical"] = query_one_value(conn, sql)

    if accepted_col:
        sql = f"""
        SELECT COUNT(*) AS c
        FROM {table_name}
        WHERE {accepted_col} IS NULL
        """
        out["totals"]["null_accepted_link"] = query_one_value(conn, sql)

    return out


def build_trait_audit(
    conn: psycopg2.extensions.connection,
    core: Dict[str, Any],
) -> Dict[str, Any]:
    table_name = core["discovered"].get("traits")
    if not table_name:
        return {"status": "missing", "message": "No traits table found"}

    columns = list_columns(conn, table_name)
    taxon_col = find_column(columns,
                            ["taxon_id", "taxa_id", "accepted_taxon_id"])
    trait_col = find_column(columns,
                            ["trait_name", "trait", "predicate", "property"])
    value_col = find_column(columns, ["trait_value", "value", "object_value"])
    source_col = find_column(columns,
                             ["source", "source_name", "dataset_source"])

    out: Dict[str, Any] = {
        "status": "ok",
        "table": table_name,
        "columns_found": {
            "taxon": taxon_col,
            "trait_name": trait_col,
            "value": value_col,
            "source": source_col,
        },
        "totals": {
            "row_count": count_rows(conn, table_name),
        },
    }

    if taxon_col:
        sql = f"SELECT COUNT(*) AS c FROM {table_name} WHERE {taxon_col} IS NOT NULL"
        out["totals"]["linked_to_taxa"] = query_one_value(conn, sql)

        sql = f"SELECT COUNT(*) AS c FROM {table_name} WHERE {taxon_col} IS NULL"
        out["totals"]["missing_taxon_link"] = query_one_value(conn, sql)

    if trait_col:
        sql = f"""
        SELECT {trait_col} AS trait_name, COUNT(*) AS count
        FROM {table_name}
        GROUP BY {trait_col}
        ORDER BY count DESC
        LIMIT 25
        """
        out["top_traits"] = query_all(conn, sql)

    if source_col:
        sql = f"""
        SELECT {source_col} AS source, COUNT(*) AS count
        FROM {table_name}
        GROUP BY {source_col}
        ORDER BY count DESC
        LIMIT 25
        """
        out["by_source"] = query_all(conn, sql)

    return out


def build_atlas_audit(
    conn: psycopg2.extensions.connection,
    core: Dict[str, Any],
) -> Dict[str, Any]:
    table_name = core["discovered"].get("atlas")
    if not table_name:
        return {"status": "missing", "message": "No atlas table found"}

    columns = list_columns(conn, table_name)
    elev_min_col = find_column(
        columns, ["min_elevation_m", "elev_min", "min_elevation"])
    elev_max_col = find_column(
        columns, ["max_elevation_m", "elev_max", "max_elevation"])
    species_col = find_column(columns, ["species_count", "n_species"])
    genus_col = find_column(columns, ["genus_count", "n_genera"])
    record_col = find_column(columns, ["records", "record_count", "n_records"])
    lat_col = find_column(columns, ["lat", "cell_lat", "latitude"])
    lon_col = find_column(columns, ["lon", "cell_lon", "longitude"])

    out: Dict[str, Any] = {
        "status": "ok",
        "table": table_name,
        "columns_found": {
            "min_elev": elev_min_col,
            "max_elev": elev_max_col,
            "species_count": species_col,
            "genus_count": genus_col,
            "record_count": record_col,
            "lat": lat_col,
            "lon": lon_col,
        },
        "totals": {
            "row_count": count_rows(conn, table_name),
        },
    }

    if elev_min_col:
        sql = f"""
        SELECT
            COUNT(*) FILTER (WHERE {elev_min_col} IS NOT NULL) AS with_min_elevation,
            COUNT(*) FILTER (WHERE {elev_min_col} IS NULL) AS missing_min_elevation
        FROM {table_name}
        """
        rows = query_all(conn, sql)
        out["min_elevation_coverage"] = rows[0] if rows else {}

    if species_col:
        sql = f"""
        SELECT MAX({species_col}) AS max_species_count,
               AVG({species_col}) AS avg_species_count
        FROM {table_name}
        """
        rows = query_all(conn, sql)
        out["species_stats"] = rows[0] if rows else {}

    if lat_col and lon_col:
        sql = f"""
        SELECT COUNT(*) AS c
        FROM {table_name}
        WHERE {lat_col} IS NOT NULL
          AND {lon_col} IS NOT NULL
        """
        out["totals"]["rows_with_coordinates"] = query_one_value(conn, sql)

    return out


def build_harvester_audit(
    conn: psycopg2.extensions.connection,
    core: Dict[str, Any],
) -> Dict[str, Any]:
    harvesters_table = core["discovered"].get("harvesters")
    runs_table = core["discovered"].get("harvester_runs")

    out: Dict[str, Any] = {
        "status": "ok",
        "harvesters_table": harvesters_table,
        "harvester_runs_table": runs_table,
    }

    if harvesters_table:
        cols = list_columns(conn, harvesters_table)
        name_col = find_column(cols, ["name", "harvester_name"])
        status_col = find_column(cols, ["status", "state"])
        updated_col = find_column(cols,
                                  ["updated_at", "last_run", "last_run_at"])

        out["harvesters_table_columns"] = {
            "name": name_col,
            "status": status_col,
            "updated": updated_col,
        }

        if name_col and status_col:
            sql = f"""
            SELECT {name_col} AS name, {status_col} AS status
            FROM {harvesters_table}
            ORDER BY {name_col}
            """
            out["registered_harvesters"] = query_all(conn, sql)

    if runs_table:
        cols = list_columns(conn, runs_table)
        name_col = find_column(cols, ["harvester_name", "name"])
        status_col = find_column(cols, ["status", "state", "run_status"])
        started_col = find_column(
            cols, ["run_time", "started_at", "created_at", "run_started_at"])

        out["harvester_runs_columns"] = {
            "name": name_col,
            "status": status_col,
            "started": started_col,
        }

        if name_col and started_col:
            sql = f"""
            SELECT {name_col} AS harvester_name,
                   MAX({started_col}) AS latest_run
            FROM {runs_table}
            GROUP BY {name_col}
            ORDER BY latest_run DESC
            """
            out["latest_runs"] = query_all(conn, sql)

        if name_col and status_col:
            sql = f"""
            SELECT {name_col} AS harvester_name,
                   {status_col} AS status,
                   COUNT(*) AS count
            FROM {runs_table}
            GROUP BY {name_col}, {status_col}
            ORDER BY count DESC
            """
            out["run_status_summary"] = query_all(conn, sql)

    if not harvesters_table and not runs_table:
        out["status"] = "missing"
        out["message"] = "No harvester metadata tables found"

    return out


def build_mapping_audit(
    conn: psycopg2.extensions.connection,
    core: Dict[str, Any],
) -> Dict[str, Any]:
    map_table = core["discovered"].get("record_taxon_map")
    if not map_table:
        return {
            "status": "missing",
            "message": "No record_taxon_map table found"
        }

    columns = list_columns(conn, map_table)
    record_col = find_column(
        columns, ["record_id", "occurrence_id", "source_record_id"])
    taxon_col = find_column(
        columns, ["taxon_id", "accepted_taxon_id", "mapped_taxon_id"])
    status_col = find_column(columns, ["status", "mapping_status"])

    out: Dict[str, Any] = {
        "status": "ok",
        "table": map_table,
        "columns_found": {
            "record": record_col,
            "taxon": taxon_col,
            "status": status_col,
        },
        "totals": {
            "row_count": count_rows(conn, map_table),
        },
    }

    if record_col:
        sql = f"SELECT COUNT(DISTINCT {record_col}) AS c FROM {map_table}"
        out["totals"]["distinct_records"] = query_one_value(conn, sql)

    if taxon_col:
        sql = f"SELECT COUNT(*) AS c FROM {map_table} WHERE {taxon_col} IS NOT NULL"
        out["totals"]["mapped_rows"] = query_one_value(conn, sql)

        sql = f"SELECT COUNT(*) AS c FROM {map_table} WHERE {taxon_col} IS NULL"
        out["totals"]["unmapped_rows"] = query_one_value(conn, sql)

    if status_col:
        sql = f"""
        SELECT {status_col} AS status, COUNT(*) AS count
        FROM {map_table}
        GROUP BY {status_col}
        ORDER BY count DESC
        """
        out["by_status"] = query_all(conn, sql)

    return out


def build_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    sections = report["sections"]
    summary: Dict[str, Any] = {
        "generated_at": report["generated_at"],
        "high_level": [],
        "warnings": [],
    }

    core = sections.get("core_discovery", {})
    discovered = core.get("discovered", {})

    summary["high_level"].append(
        f"Occurrences table: {discovered.get('occurrences')}")
    summary["high_level"].append(f"Images table: {discovered.get('images')}")
    summary["high_level"].append(f"Taxa table: {discovered.get('taxa')}")
    summary["high_level"].append(f"Traits table: {discovered.get('traits')}")
    summary["high_level"].append(f"Atlas table: {discovered.get('atlas')}")
    summary["high_level"].append(
        f"Harvester table: {discovered.get('harvesters')}")
    summary["high_level"].append(
        f"Harvester runs table: {discovered.get('harvester_runs')}")
    summary["high_level"].append(
        f"Record-taxon map table: {discovered.get('record_taxon_map')}")

    occ = sections.get("occurrence_audit", {})
    if occ.get("status") == "missing":
        summary["warnings"].append("No occurrence table discovered.")
    else:
        missing_elev = ((occ.get("elevation") or {}).get("missing_elevation"))
        if missing_elev and missing_elev > 0:
            summary["warnings"].append(
                f"Occurrence rows missing elevation: {missing_elev}")

    img = sections.get("image_audit", {})
    if img.get("status") == "missing":
        summary["warnings"].append("No image/media table discovered.")
    else:
        missing_tax_link = (img.get("totals")
                            or {}).get("missing_taxonomy_link")
        if missing_tax_link and missing_tax_link > 0:
            summary["warnings"].append(
                f"Images missing taxonomy link: {missing_tax_link}")

    traits = sections.get("trait_audit", {})
    if traits.get("status") == "missing":
        summary["warnings"].append("No traits table discovered.")

    atlas = sections.get("atlas_audit", {})
    if atlas.get("status") == "missing":
        summary["warnings"].append("No atlas table discovered.")

    mapping = sections.get("mapping_audit", {})
    if mapping.get("status") == "missing":
        summary["warnings"].append("No record-taxon mapping table discovered.")

    return summary


def render_text_report(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("ORCHID CONTINUUM SENTINEL REPORT")
    lines.append("=" * 40)
    lines.append(f"Generated at: {report['generated_at']}")
    lines.append("")

    summary = report.get("summary", {})
    lines.append("HIGH LEVEL")
    lines.append("-" * 10)
    for item in summary.get("high_level", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("WARNINGS")
    lines.append("-" * 8)
    warnings = summary.get("warnings", [])
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("SECTIONS")
    lines.append("-" * 8)
    for section_name, section_data in report["sections"].items():
        lines.append(f"[{section_name}]")
        lines.append(json.dumps(section_data, indent=2, default=str))
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    report: Dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "sections": {},
    }

    safe_print("\nORCHID CONTINUUM SENTINEL")
    safe_print("=" * 30)

    try:
        conn = connect()
    except Exception as e:
        safe_print(f"FATAL: could not connect to DATABASE_URL: {e}")
        return 2

    try:
        section_wrapper(report, "schema_inventory",
                        lambda: build_schema_inventory(conn))
        section_wrapper(report, "core_discovery",
                        lambda: build_core_discovery(conn))

        core = report["sections"].get("core_discovery",
                                      {}).get("discovered", {})
        wrapped_core = {"discovered": core}

        section_wrapper(report, "occurrence_audit",
                        lambda: build_occurrence_audit(conn, wrapped_core))
        section_wrapper(report, "image_audit",
                        lambda: build_image_audit(conn, wrapped_core))
        section_wrapper(report, "taxonomy_audit",
                        lambda: build_taxonomy_audit(conn, wrapped_core))
        section_wrapper(report, "trait_audit",
                        lambda: build_trait_audit(conn, wrapped_core))
        section_wrapper(report, "atlas_audit",
                        lambda: build_atlas_audit(conn, wrapped_core))
        section_wrapper(report, "harvester_audit",
                        lambda: build_harvester_audit(conn, wrapped_core))
        section_wrapper(report, "mapping_audit",
                        lambda: build_mapping_audit(conn, wrapped_core))

        report["summary"] = build_summary(report)

        with open(REPORT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

        text_report = render_text_report(report)
        with open(REPORT_TXT, "w", encoding="utf-8") as f:
            f.write(text_report)

        safe_print("\nSUMMARY")
        safe_print("-" * 10)
        for item in report["summary"].get("high_level", []):
            safe_print(item)

        safe_print("\nWARNINGS")
        safe_print("-" * 10)
        warnings = report["summary"].get("warnings", [])
        if warnings:
            for w in warnings:
                safe_print(w)
        else:
            safe_print("None")

        safe_print(f"\nWrote {REPORT_JSON}")
        safe_print(f"Wrote {REPORT_TXT}")
        safe_print("\nDONE")
        return 0

    except Exception as e:
        safe_print(f"FATAL: sentinel failed: {e}")
        safe_print(traceback.format_exc())
        return 1

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
