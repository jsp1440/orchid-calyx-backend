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

AUDIT_EDGE_TYPES: dict[str, tuple[str, ...]] = {
    "taxonomy_to_images": ("has_image", "taxonomy_to_images", "depicts"),
    "taxonomy_to_occurrences": ("occurs_at",),
    "taxonomy_to_elevation": ("has_elevation",),
    "taxonomy_to_climate": ("experiences_climate",),
    "taxonomy_to_literature": ("documented_by",),
    "taxonomy_to_pollinators": ("associated_with_pollinator",),
    "taxonomy_to_mycorrhiza": ("associated_with_mycorrhiza",),
    "taxonomy_to_habitat": ("occupies_habitat",),
    "taxonomy_to_conservation": ("has_conservation_assessment",),
}

AUDIT_TARGET_DOMAIN_VALUES: dict[str, tuple[str, ...]] = {
    "taxonomy_to_images": ("images", "image", "media"),
    "taxonomy_to_occurrences": ("occurrences", "occurrence"),
    "taxonomy_to_elevation": ("elevation",),
    "taxonomy_to_climate": ("climate",),
    "taxonomy_to_literature": ("literature", "publication"),
    "taxonomy_to_pollinators": ("pollinators", "pollinator"),
    "taxonomy_to_mycorrhiza": ("mycorrhiza", "fungus"),
    "taxonomy_to_habitat": ("habitat",),
    "taxonomy_to_conservation": (
        "conservation",
        "conservation_assessment",
    ),
}


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
    taxonomy_table = _first_existing(
        cur,
        ("public.orchid_taxonomy", "oc_core.taxonomy", "public.taxonomy"),
    )
    image_table = _first_existing(
        cur,
        ("public.orchid_images", "oc_core.media_assets", "public.images"),
    )
    if not taxonomy_table or not image_table:
        return {
            "state": "unavailable",
            "taxonomy_table": taxonomy_table,
            "image_table": image_table,
            "detail": "Required taxonomy or image table was not found.",
        }

    tax_cols = _columns(cur, taxonomy_table)
    image_cols = _columns(cur, image_table)
    tax_pk = next(
        (column for column in ("id", "taxon_id", "taxonomy_id") if column in tax_cols),
        None,
    )
    image_fk = next(
        (
            column
            for column in ("taxonomy_id", "taxon_id", "accepted_taxon_id")
            if column in image_cols
        ),
        None,
    )
    if not tax_pk or not image_fk:
        return {
            "state": "unavailable",
            "taxonomy_table": taxonomy_table,
            "image_table": image_table,
            "detail": (
                "Canonical taxonomy primary key or image taxon foreign key "
                "was not found."
            ),
        }

    total_taxa = _scalar(cur, f"SELECT COUNT(*) FROM {taxonomy_table}")
    total_images = _scalar(cur, f"SELECT COUNT(*) FROM {image_table}")
    linked_images = _scalar(
        cur,
        f"SELECT COUNT(*) FROM {image_table} WHERE {image_fk} IS NOT NULL",
    )
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
        "broken_taxonomy_targets": Metric(
            "available",
            broken_targets,
            linked_images,
        ).as_dict(),
        "taxa_with_images": Metric("available", linked_taxa, total_taxa).as_dict(),
        "interpretation": "relational_linkage_only",
    }


def _empty_relationship_metrics() -> dict[str, dict[str, Any]]:
    return {
        name: {"state": "unavailable", "value": None}
        for name in AUDIT_EDGE_TYPES
    }


def _measure_relationship_edge_types(
    cur,
    edge_table: str,
    relationship_column: str,
    total_edges: int,
) -> dict[str, dict[str, Any]]:
    measured: dict[str, dict[str, Any]] = {}
    for name, edge_types in AUDIT_EDGE_TYPES.items():
        placeholders = ", ".join("%s" for _ in edge_types)
        count = _scalar(
            cur,
            (
                f"SELECT COUNT(*) FROM {edge_table} "
                f"WHERE {relationship_column} IN ({placeholders})"
            ),
            edge_types,
        )
        measured[name] = Metric("available", count, total_edges).as_dict()
    return measured


def _measure_relationship_domains(
    cur,
    edge_table: str,
    source_domain: str,
    target_domain: str,
    total_edges: int,
) -> dict[str, dict[str, Any]]:
    measured: dict[str, dict[str, Any]] = {}
    for name, target_values in AUDIT_TARGET_DOMAIN_VALUES.items():
        placeholders = ", ".join("%s" for _ in target_values)
        count = _scalar(
            cur,
            (
                f"SELECT COUNT(*) FROM {edge_table} "
                f"WHERE {source_domain} = %s "
                f"AND {target_domain} IN ({placeholders})"
            ),
            ("taxonomy", *target_values),
        )
        measured[name] = Metric("available", count, total_edges).as_dict()
    return measured


def _measure_integrity(
    cur,
    edge_table: str,
    source_id: str | None,
    target_id: str | None,
    relationship_type: str | None,
) -> dict[str, Any]:
    if not source_id or not target_id:
        return {
            "state": "unavailable",
            "detail": "Edge identity columns not recognized.",
        }

    null_endpoints = _scalar(
        cur,
        (
            f"SELECT COUNT(*) FROM {edge_table} "
            f"WHERE {source_id} IS NULL OR {target_id} IS NULL"
        ),
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

    orphan_edges = 0
    if (
        edge_table == "oc_graph.kg_edges"
        and source_id == "from_node_id"
        and target_id == "to_node_id"
        and _table_exists(cur, "oc_graph.kg_nodes")
    ):
        orphan_edges = _scalar(
            cur,
            """
            SELECT COUNT(*)
            FROM oc_graph.kg_edges e
            LEFT JOIN oc_graph.kg_nodes f ON f.kg_node_id = e.from_node_id
            LEFT JOIN oc_graph.kg_nodes t ON t.kg_node_id = e.to_node_id
            WHERE f.kg_node_id IS NULL OR t.kg_node_id IS NULL
            """,
        )

    return {
        "state": "available",
        "null_endpoint_edges": null_endpoints,
        "orphan_edges": orphan_edges,
        "duplicate_edges": duplicate_edges,
        "passed": (
            null_endpoints == 0 and orphan_edges == 0 and duplicate_edges == 0
        ),
    }


def measure_graph_materialization(cur) -> dict[str, Any]:
    edge_table = _first_existing(
        cur,
        (
            "oc_graph.kg_edges",
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
            "relationships": _empty_relationship_metrics(),
            "detail": (
                "No recognized persisted graph-edge table exists; relational links "
                "must not be reported as graph materialization."
            ),
        }

    cols = _columns(cur, edge_table)
    source_domain = next(
        (column for column in ("source_domain", "from_domain") if column in cols),
        None,
    )
    target_domain = next(
        (column for column in ("target_domain", "to_domain") if column in cols),
        None,
    )
    relationship_type = next(
        (
            column
            for column in ("relationship_type", "predicate", "edge_type")
            if column in cols
        ),
        None,
    )
    source_id = next(
        (
            column
            for column in (
                "source_record_id",
                "source_id",
                "from_id",
                "from_node_id",
            )
            if column in cols
        ),
        None,
    )
    target_id = next(
        (
            column
            for column in (
                "target_record_id",
                "target_id",
                "to_id",
                "to_node_id",
            )
            if column in cols
        ),
        None,
    )

    total_edges = _scalar(cur, f"SELECT COUNT(*) FROM {edge_table}")
    relationships = _empty_relationship_metrics()
    if relationship_type:
        relationships = _measure_relationship_edge_types(
            cur,
            edge_table,
            relationship_type,
            total_edges,
        )
    elif source_domain and target_domain:
        relationships = _measure_relationship_domains(
            cur,
            edge_table,
            source_domain,
            target_domain,
            total_edges,
        )

    integrity = _measure_integrity(
        cur,
        edge_table,
        source_id,
        target_id,
        relationship_type,
    )
    result: dict[str, Any] = {
        "state": "available",
        "edge_table": edge_table,
        "total_edges": total_edges,
        "relationships": relationships,
        "integrity": integrity,
        "knowledge_graph_node_edge_integrity": integrity,
    }
    # Preserve the original direct keys while exposing the complete relationship
    # map for newer audit/reporting consumers.
    result.update(relationships)
    return result


def run_live_graph_audit(cur) -> dict[str, Any]:
    relational = measure_taxonomy_images(cur)
    graph = measure_graph_materialization(cur)
    blockers: list[str] = []
    missing_relationships: list[str] = []

    if relational.get("state") != "available":
        blockers.append("taxonomy_image_relational_measurement_unavailable")

    if graph.get("state") != "available":
        blockers.append("graph_materialization_measurement_unavailable")
        missing_relationships.extend(AUDIT_EDGE_TYPES)
    else:
        relationships = graph.get("relationships") or {}
        for name in AUDIT_EDGE_TYPES:
            metric = relationships.get(name) or {}
            if metric.get("state") != "available":
                blockers.append(f"{name}_graph_edge_measurement_unavailable")
                missing_relationships.append(name)
            elif int(metric.get("value") or 0) == 0:
                blockers.append(f"{name}_graph_edges_absent")
                missing_relationships.append(name)

    integrity = graph.get("integrity") or {}
    if graph.get("state") == "available":
        if integrity.get("state") != "available":
            blockers.append("graph_integrity_measurement_unavailable")
        elif not integrity.get("passed"):
            blockers.append("graph_integrity_failed")

    return {
        "contract": "calyx-live-graph-audit-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "relational": {"taxonomy_to_images": relational},
        "graph": graph,
        "missing_relationships": missing_relationships,
        "knowledge_graph_node_edge_integrity": integrity,
        "blockers": blockers,
        "homepage_ready": not blockers,
        "warning": (
            "Relational foreign-key linkage and persisted Knowledge Graph "
            "materialization are intentionally separate measurements."
        ),
    }
