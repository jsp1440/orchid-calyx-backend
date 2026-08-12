"""Governed live-schema materialization for graph domains lacking static queries.

Habitat and elevation are configured production domains and already have graph
adapters, but the static source registry intentionally withholds them because the
live table/crosswalk shape has not been frozen. This module closes that gap
without guessing: it inspects only fixed candidate relations, requires a stable
record key and canonical taxon key on the *same* relation, requires at least one
row that resolves to an existing taxon node, and then builds a SELECT-only
projection.

Dry-run is the default. Production publication is explicit, transactional, and
uses the same single-writer publisher as the canonical materializer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .controlled_dry_run import run_controlled_dry_run
from .domain_sources import by_domain
from .full_integration import DOMAIN_TABLE_CANDIDATES, IDENTITY_CANDIDATES, TAXON_KEY_CANDIDATES
from .production_publish import publish_to_production
from .publisher import DomainAdapter, EdgeSpec, NodeSpec, canonical_key
from .repository import PostgresGraphRepository
from .source_registry import assert_safe_sql
from .sources import PostgresSourceProvider

CONFIRMATION_TOKEN = "PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS"
DYNAMIC_DOMAINS = ("habitat", "elevation")
DEFAULT_MAX_ROWS_PER_DOMAIN = 10_000


@dataclass(frozen=True, slots=True)
class VerifiedProjection:
    domain: str
    source: str
    source_pk_column: str
    taxon_pk_column: str
    matched_rows: int
    sql: str
    node_type: str
    edge_type: str


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _relation_exists(cur, qualified: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (qualified,))
    row = cur.fetchone()
    return bool(_row_value(row, "present")) if row else False


def _relation_columns(cur, schema: str, table: str) -> tuple[str, ...]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return tuple(
        str(row.get("column_name") if isinstance(row, dict) else row[0])
        for row in cur.fetchall()
    )


def _first(candidates: Iterable[str], columns: Iterable[str]) -> str | None:
    available = set(columns)
    return next((candidate for candidate in candidates if candidate in available), None)


def projection_sql(
    *,
    source: str,
    source_pk_column: str,
    taxon_pk_column: str,
) -> str:
    """Build the fixed SELECT-only taxon-linked projection used for dry/publish."""
    sql = (
        f"SELECT s.{source_pk_column} AS source_pk, "
        f"s.{taxon_pk_column} AS taxon_pk, to_jsonb(s) AS source_payload "
        f"FROM {source} s "
        f"WHERE s.{source_pk_column} IS NOT NULL "
        f"AND s.{taxon_pk_column} IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM oc_graph.kg_nodes k "
        "WHERE k.node_type='taxon' "
        f"AND k.source_pk=s.{taxon_pk_column}::text)"
    )
    assert_safe_sql(sql)
    return sql


def discover_projection(dsn: str, domain: str) -> VerifiedProjection:
    """Discover one verified source relation for habitat or elevation.

    Candidate relation names come only from the fixed full-integration registry.
    A relation is usable only when identity and taxon columns coexist on that
    exact relation and at least one row resolves to the persisted taxon backbone.
    """
    normalized = str(domain).strip().lower()
    if normalized not in DYNAMIC_DOMAINS:
        raise ValueError(f"DYNAMIC_GRAPH_DOMAIN_NOT_ALLOWED:{normalized}")
    if not dsn or not str(dsn).strip():
        raise ValueError("DATABASE_URL_REQUIRED")

    configured = by_domain()[normalized]
    candidates = DOMAIN_TABLE_CANDIDATES.get(normalized, ())

    import psycopg

    diagnostics: list[str] = []
    with psycopg.connect(dsn, connect_timeout=8) as conn, conn.cursor() as cur:
        for candidate in candidates:
            qualified = candidate.qualified
            if not _relation_exists(cur, qualified):
                diagnostics.append(f"{qualified}:missing")
                continue
            columns = _relation_columns(cur, candidate.schema, candidate.table)
            source_pk = _first(IDENTITY_CANDIDATES, columns)
            taxon_pk = _first(TAXON_KEY_CANDIDATES, columns)
            if source_pk is None or taxon_pk is None:
                diagnostics.append(
                    f"{qualified}:identity={source_pk or 'missing'},taxon={taxon_pk or 'missing'}"
                )
                continue
            sql = projection_sql(
                source=qualified,
                source_pk_column=source_pk,
                taxon_pk_column=taxon_pk,
            )
            cur.execute(f"SELECT COUNT(*) FROM ({sql}) AS verified_source")
            row = cur.fetchone()
            matched = int(_row_value(row, "count") or 0) if row else 0
            if matched <= 0:
                diagnostics.append(f"{qualified}:zero_taxon_resolved_rows")
                continue
            return VerifiedProjection(
                domain=normalized,
                source=qualified,
                source_pk_column=source_pk,
                taxon_pk_column=taxon_pk,
                matched_rows=matched,
                sql=sql,
                node_type=str(configured.node_type),
                edge_type=str(configured.edge_type),
            )

    detail = ";".join(diagnostics) or "no_candidate_relations"
    raise ValueError(f"NO_VERIFIED_DYNAMIC_PROJECTION:{normalized}:{detail}")


def _dynamic_adapter(projection: VerifiedProjection) -> DomainAdapter:
    """Preserve the complete source row as provenance-bearing graph payload."""

    def produce(rows):
        nodes: list[NodeSpec] = []
        edges: list[EdgeSpec] = []
        seen: set[str] = set()
        for row in rows:
            source_pk = row.get("source_pk")
            taxon_pk = row.get("taxon_pk")
            if source_pk is None or taxon_pk is None:
                raise ValueError(
                    f"{projection.domain} dynamic adapter requires source_pk/taxon_pk"
                )
            payload = dict(row.get("source_payload") or {})
            label = next(
                (
                    str(payload[field])
                    for field in (
                        "habitat_name",
                        "habitat_type",
                        "elevation_label",
                        "scientific_name",
                    )
                    if payload.get(field) not in (None, "")
                ),
                f"{projection.node_type}:{source_pk}",
            )
            node_key = canonical_key(projection.node_type, source_pk)
            if node_key not in seen:
                seen.add(node_key)
                nodes.append(
                    NodeSpec(
                        node_type=projection.node_type,
                        source_pk=source_pk,
                        display_label=label,
                        source_table=projection.source,
                        evidence_class="normalized",
                        payload={
                            "source_relation": projection.source,
                            "source_payload": payload,
                            "projection_contract": "verified-live-schema-v1",
                        },
                    )
                )
            edges.append(
                EdgeSpec(
                    edge_type=projection.edge_type,
                    from_key=canonical_key("taxon", taxon_pk),
                    to_key=node_key,
                    source_table=projection.source,
                    source_pk=source_pk,
                    evidence_class="normalized",
                    rule_name=f"{projection.domain}_verified_live_projection",
                    payload={"projection_contract": "verified-live-schema-v1"},
                )
            )
        return nodes, edges

    return DomainAdapter(
        domain=projection.domain,
        source_table=projection.source,
        produce=produce,
        required_identifiers=("source_pk", "taxon_pk"),
    )


def materialize_dynamic_relationship(
    dsn: str,
    *,
    domain: str,
    execute: bool = False,
    confirmation: str | None = None,
    batch_size: int = 500,
    max_dry_run_rows: int = DEFAULT_MAX_ROWS_PER_DOMAIN,
) -> dict[str, Any]:
    """Verify, dry-run, or transactionally publish habitat/elevation edges."""
    if not 1 <= int(batch_size) <= 5_000:
        raise ValueError("BATCH_SIZE_OUT_OF_RANGE:1..5000")
    if int(max_dry_run_rows) < 1:
        raise ValueError("DRY_RUN_ROW_LIMIT_MUST_BE_POSITIVE")
    if execute and confirmation != CONFIRMATION_TOKEN:
        raise PermissionError("GRAPH_PUBLICATION_CONFIRMATION_REQUIRED")

    projection = discover_projection(dsn, domain)
    adapter = _dynamic_adapter(projection)
    queries = {projection.domain: projection.sql}

    if not execute:
        report = run_controlled_dry_run(
            PostgresGraphRepository(dsn),
            PostgresSourceProvider(dsn, queries),
            adapters=(adapter,),
            max_rows_per_domain=int(max_dry_run_rows),
            batch_size=int(batch_size),
        )
        report["dynamic_projection"] = {
            "contract": "calyx-verified-live-projection-v1",
            "domain": projection.domain,
            "source": projection.source,
            "source_pk_column": projection.source_pk_column,
            "taxon_pk_column": projection.taxon_pk_column,
            "taxon_resolved_rows": projection.matched_rows,
            "production_graph_mutation": False,
        }
        return report

    report = publish_to_production(
        dsn,
        adapters=(adapter,),
        batch_size=int(batch_size),
        queries=queries,
    )
    report["dynamic_projection"] = {
        "contract": "calyx-verified-live-projection-v1",
        "domain": projection.domain,
        "source": projection.source,
        "source_pk_column": projection.source_pk_column,
        "taxon_pk_column": projection.taxon_pk_column,
        "taxon_resolved_rows": projection.matched_rows,
        "production_graph_mutation": bool(report.get("committed")),
        "transactional": True,
        "single_writer_lock": True,
    }
    return report
