"""Read-only adapters from governed Knowledge Graph sources into matrix assertions.

This module is intentionally narrow: only domains whose source registry already
has a verified, enabled SELECT are eligible. Source rows are positive evidence
records, so they become ``present`` assertions only; missing rows never become
biological absence.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from runtime.knowledge_graph.source_registry import assert_safe_sql, registry_by_domain
from runtime.matrix_relationship import RelationshipAssertion

_DIMENSION_TO_DOMAIN = {
    "pollinator": "pollinators",
    "mycorrhizal_partner": "mycorrhiza",
    "literature": "literature",
}


def governed_source_dimensions() -> list[str]:
    """Return matrix dimensions backed by enabled canonical source queries."""
    registry = registry_by_domain()
    return sorted(
        dimension
        for dimension, domain in _DIMENSION_TO_DOMAIN.items()
        if domain in registry and registry[domain].enabled and registry[domain].sql
    )


def _bounded_confidence(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return confidence if 0 <= confidence <= 1 else None


def _object_identity(dimension: str, row: dict[str, Any]) -> tuple[str, str]:
    if dimension == "pollinator":
        label = str(row.get("partner_taxon_name") or "").strip()
        if not label:
            raise ValueError("pollinator source row is missing partner_taxon_name")
        return f"pollinator:{label.casefold()}", label

    if dimension == "mycorrhizal_partner":
        label = str(row.get("fungal_name") or "").strip()
        if not label:
            raise ValueError("mycorrhiza source row is missing fungal_name")
        fungal_id = row.get("fungal_taxon_id")
        object_id = (
            f"fungus-taxon:{fungal_id}"
            if fungal_id not in (None, "")
            else f"fungus:{label.casefold()}"
        )
        return object_id, label

    if dimension == "literature":
        label = str(row.get("title") or "").strip()
        if not label:
            raise ValueError("literature source row is missing title")
        doi = str(row.get("doi") or "").strip()
        source_pk = str(row.get("source_pk") or "").strip()
        object_id = f"doi:{doi.casefold()}" if doi else f"literature:{source_pk}"
        if not source_pk and not doi:
            raise ValueError("literature source row is missing source identity")
        return object_id, label

    raise ValueError(f"unsupported governed matrix dimension: {dimension}")


def rows_to_assertions(
    dimension: str,
    rows: list[dict[str, Any]],
) -> list[RelationshipAssertion]:
    """Adapt canonical source rows without inventing absent/unknown states."""
    domain = _DIMENSION_TO_DOMAIN.get(dimension)
    if not domain:
        raise ValueError(f"unsupported governed matrix dimension: {dimension}")

    registry = registry_by_domain()
    query = registry.get(domain)
    if query is None or not query.enabled or not query.sql:
        raise ValueError(f"governed source unavailable for dimension: {dimension}")

    assertions: list[RelationshipAssertion] = []
    for row in rows:
        subject_id = str(row.get("taxon_pk") or "").strip()
        subject_label = str(row.get("subject_label") or "").strip()
        source_pk = str(row.get("source_pk") or "").strip()
        if not subject_id or not subject_label or not source_pk:
            raise ValueError("governed source row is missing taxon/source identity")

        object_id, object_label = _object_identity(dimension, row)
        provenance = {
            "source_domain": domain,
            "source_query_id": query.query_id,
            "source_pk": source_pk,
        }
        for key in (
            "evidence_class",
            "evidence_citation",
            "citation",
            "doi",
            "created_at",
            "updated_at",
            "year",
        ):
            if row.get(key) not in (None, ""):
                provenance[key] = row[key]

        assertions.append(
            RelationshipAssertion(
                subject_id=subject_id,
                subject_label=subject_label,
                dimension=dimension,
                object_id=object_id,
                object_label=object_label,
                state="present",
                confidence=_bounded_confidence(row.get("confidence_score")),
                provenance=provenance,
            )
        )
    return assertions


def load_governed_assertions(
    database_url: str,
    *,
    dimension: str,
    subject_ids: list[str] | None = None,
    limit: int = 5000,
) -> list[RelationshipAssertion]:
    """Load bounded canonical evidence through the existing read-only registry."""
    if limit < 1 or limit > 5000:
        raise ValueError("limit must be between 1 and 5000")

    domain = _DIMENSION_TO_DOMAIN.get(dimension)
    if not domain:
        raise ValueError(f"unsupported governed matrix dimension: {dimension}")
    query = registry_by_domain().get(domain)
    if query is None or not query.enabled or not query.sql:
        raise ValueError(f"governed source unavailable for dimension: {dimension}")

    assert_safe_sql(query.sql)
    registered_sql = query.sql.strip().rstrip(";")
    sql = (
        "select s.*, k.display_label as subject_label "
        f"from ({registered_sql}) s "
        "join oc_graph.kg_nodes k "
        "on k.node_type='taxon' and k.source_pk=s.taxon_pk::text"
    )
    params: list[Any] = []
    if subject_ids:
        sql += " where s.taxon_pk::text = any(%s)"
        params.append([str(value) for value in subject_ids])
    sql += " order by s.taxon_pk::text, s.source_pk::text limit %s"
    params.append(limit)
    assert_safe_sql(sql)

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("set transaction read only")
            rows = connection.execute(sql, params).fetchall()

    return rows_to_assertions(dimension, list(rows))
