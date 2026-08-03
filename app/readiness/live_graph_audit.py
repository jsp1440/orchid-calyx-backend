"""Read-only live homepage/Knowledge Graph readiness measurements.

The legacy executive audit accepted an in-memory list of RelationshipLink objects.
An empty/unpopulated list therefore reported every scientific relationship as
missing even when relational foreign keys existed. This module queries the live
PostgreSQL catalog and data, and deliberately reports relational linkage and graph
materialization as separate evidence states.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class Metric:
    state: str
    value: int | float | None = None
    denominator: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        percentage = None
        if self.value is not None and self.denominator:
            percentage = round((float(self.value) / self.denominator) * 100, 4)
        return {
            "state": self.state,
            "value": self.value,
            "denominator": self.denominator,
            "percentage": percentage,
            "detail": self.detail,
        }


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (table_name,))
    row = cur.fetchone()
    return bool(row[0] if not isinstance(row, dict) else row["present"])


def _columns(cur, table_name: str) -> set[str]:
    schema, _, table = table_name.partition(".")
    if not table:
        schema, table = "public", schema
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return {
        str(row[0] if not isinstance(row, dict) else row["column_name"])
        for row in cur.fetchall()
    }


def _scalar(cur, sql: str, params: Iterable[Any] = ()) -> int:
    cur.execute(sql, tuple(params))
    row = cur.fetchone()
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return int(value or 0)


def _first_existing(cur, candidates: tuple[str, ...]) -> str | None:
    return next((name for name in candidates if _table_exists(cur, name)), None)


def measure_taxonomy_images(cur) -> dict[str, Any]:
    taxonomy_table = _first_existing(cur, ("public.orchid_taxonomy", "oc_core.taxonomy", "public.taxonomy"))
    image_table = _first_existing(cur, ("public.orchid_images", "oc_core.media_assets", "public.images"))
    if not taxonomy_table or not image_table:
        return {
            "state": "unavailable",
            "taxonomy_table": taxonomy_table,
            "image_table": image_table,
            "detail": "Required taxonomy or image table was not found.",
        }

    tax_cols = _columns(cur, taxonomy_table)
    image_cols = _columns(cur, image_table)
    tax_pk = next((c for c in ("id", "taxon_id", "taxonomy_id") if c in tax_cols), None)
    image_fk = next((c for c in ("taxonomy_id", "taxon_id", "accepted_taxon_id") if c in image_cols), None)
    if not tax_pk or not image_fk:
        return {
            "state": "unavailable",
            "taxonomy_table": taxonomy_table,
            "image_table": image_table,
            "detail": "Canonical taxonomy primary key or image taxon foreign key was not found.",
        }

    total_taxa = _scalar(cur, f"SELECT COUNT(*) FROM {taxonomy_table}")
    total_images = _scalar(cur, f"SELECT COUNT(*) FROM {image_table}")
    linked_images = _scalar(cur, f"SELECT COUNT(*) FROM {image_table} WHERE {image_fk} IS NOT NULL")
    unlinked_images = total_images - linked_images
    broken_targets = _scalar(
        cur,
        f"""
        SELECT COUNT(*)
        FROM {image_table} i
        LEFT JOIN {taxonomy_table} t ON t.{tax_pk} = i.{image_fk}
        WHERE i.{image_fk} IS NOT NULL AND t.{tax_pk} IS NULL
        """,
    )
    valid_links = linked_images - broken_targets
    linked_taxa = _scalar(
        cur,
        f"""
        SELECT COUNT(DISTINCT i.{image_fk})
        FROM {image_table} i
        JOIN {taxonomy_table} t ON t.{tax_pk} = i.{image_fk}
        """,
    )

    return {
        "state": "available",
        "taxonomy_table": taxonomy_table,
        "image_table": image_table,
        "taxonomy_key": tax_pk,
        "image_taxonomy_key": image_fk,
        "total_taxa": total_taxa,
        "total_images": total_images,
        "linked_images": Metric("available", valid_links, total_images).as_dict(),
        "unlinked_images": Metric("available", unlinked_images, total_images).as_dict(),
        "broken_taxonomy_targets": Metric("available", broken_targets, linked_images).as_dict(),
        "taxa_with_images": Metric("available", linked_taxa, total_taxa).as_dict(),
        "interpretation": "relational_linkage_only",
    }


def measure_graph_materialization(cur) -> dict[str, Any]:
    edge_table = _first_existing(
        cur,
        (
            "oc_graph.relationship_edges",
            "oc_core.relationship_links",
            "public.knowledge_graph_edges",
            "public.relationships",
        ),
    )
    if not edge_table:
        return {
            "state": "unavailable",
            "edge_table": None,
            "detail": "No recognized persisted graph-edge table exists; relational links must not be reported as graph materialization.",
        }

    cols = _columns(cur, edge_table)
    source_domain = next((c for c in ("source_domain", "from_domain") if c in cols), None)
    target_domain = next((c for c in ("target_domain", "to_domain") if c in cols), None)
    relationship_type = next((c for c in ("relationship_type", "predicate", "edge_type") if c in cols), None)
    source_id = next((c for c in ("source_record_id", "source_id", "from_id") if c in cols), None)
    target_id = next((c for c in ("target_record_id", "target_id", "to_id") if c in cols), None)

    total_edges = _scalar(cur, f"SELECT COUNT(*) FROM {edge_table}")
    result: dict[str, Any] = {
        "state": "available",
        "edge_table": edge_table,
        "total_edges": total_edges,
        "taxonomy_to_images": {"state": "unavailable", "value": None},
        "integrity": {"state": "unavailable", "detail": "Edge identity columns not recognized."},
    }

    if source_domain and target_domain:
        count = _scalar(
            cur,
            f"SELECT COUNT(*) FROM {edge_table} WHERE {source_domain} = %s AND {target_domain} IN (%s, %s)",
            ("taxonomy", "images", "image"),
        )
        result["taxonomy_to_images"] = Metric("available", count, total_edges).as_dict()
    elif relationship_type:
        count = _scalar(
            cur,
            f"SELECT COUNT(*) FROM {edge_table} WHERE {relationship_type} IN (%s, %s, %s)",
            ("taxonomy_to_images", "has_image", "depicts"),
        )
        result["taxonomy_to_images"] = Metric("available", count, total_edges).as_dict()

    if source_id and target_id:
        null_endpoints = _scalar(
            cur,
            f"SELECT COUNT(*) FROM {edge_table} WHERE {source_id} IS NULL OR {target_id} IS NULL",
        )
        duplicate_edges = 0
        if relationship_type:
            duplicate_edges = _scalar(
                cur,
                f"""
                SELECT COALESCE(SUM(n - 1), 0)
                FROM (
                    SELECT COUNT(*) AS n
                    FROM {edge_table}
                    GROUP BY {source_id}, {target_id}, {relationship_type}
                    HAVING COUNT(*) > 1
                ) duplicates
                """,
            )
        result["integrity"] = {
            "state": "available",
            "null_endpoint_edges": null_endpoints,
            "duplicate_edges": duplicate_edges,
            "passed": null_endpoints == 0 and duplicate_edges == 0,
        }

    return result


def run_live_graph_audit(cur) -> dict[str, Any]:
    relational = measure_taxonomy_images(cur)
    graph = measure_graph_materialization(cur)
    blockers: list[str] = []
    if relational.get("state") != "available":
        blockers.append("taxonomy_image_relational_measurement_unavailable")
    if graph.get("state") != "available":
        blockers.append("graph_materialization_measurement_unavailable")
    elif (graph.get("taxonomy_to_images") or {}).get("state") != "available":
        blockers.append("taxonomy_image_graph_edge_measurement_unavailable")
    elif int((graph.get("taxonomy_to_images") or {}).get("value") or 0) == 0:
        blockers.append("taxonomy_image_graph_edges_absent")
    if (graph.get("integrity") or {}).get("state") != "available":
        blockers.append("graph_integrity_measurement_unavailable")
    elif not (graph.get("integrity") or {}).get("passed"):
        blockers.append("graph_integrity_failed")

    return {
        "contract": "calyx-live-graph-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "relational": {"taxonomy_to_images": relational},
        "graph": graph,
        "blockers": blockers,
        "homepage_ready": not blockers,
        "warning": "Relational foreign-key linkage and persisted Knowledge Graph materialization are intentionally separate measurements.",
    }
