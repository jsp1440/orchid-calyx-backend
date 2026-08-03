"""Safe dynamic source projection for full Knowledge Graph integration.

This module converts a live catalog inventory into executable SELECT-only source
projections when a table exposes both a stable record identity and a canonical
taxon identifier. It deliberately refuses fuzzy/name-only publication and
reports a blocker instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .full_integration import DomainInventory
from .source_registry import assert_safe_sql


@dataclass(frozen=True)
class ProjectionPlan:
    domain: str
    source: str | None
    state: str
    sql: str | None
    source_pk_column: str | None
    taxon_pk_column: str | None
    limitation: str | None = None

    @property
    def executable(self) -> bool:
        return self.state == "ready" and bool(self.sql)


PREFERRED_ID_COLUMNS = (
    "id", "record_id", "occurrence_id", "image_id", "media_id",
    "publication_id", "trait_id", "assessment_id", "interaction_id",
    "evidence_id",
)

PREFERRED_TAXON_COLUMNS = (
    "canonical_taxon_id", "taxonomy_id", "taxon_id", "accepted_taxon_id",
)


def _first(candidates: Iterable[str], available: Iterable[str]) -> str | None:
    pool = set(available)
    return next((name for name in candidates if name in pool), None)


def build_projection(inventory: DomainInventory) -> ProjectionPlan:
    """Build a conservative source projection from a catalog inventory row.

    Only direct canonical-id projections are executable. Sources with no stable
    identity or no canonical taxon key remain blocked for explicit adapter work.
    """
    if inventory.configured_status != "production":
        return ProjectionPlan(
            domain=inventory.domain, source=None, state="withheld", sql=None,
            source_pk_column=None, taxon_pk_column=None,
            limitation=inventory.limitation or "Domain is not production evidence.",
        )
    if not inventory.discovered_sources:
        return ProjectionPlan(
            domain=inventory.domain, source=None, state="unavailable", sql=None,
            source_pk_column=None, taxon_pk_column=None,
            limitation="No live source relation was discovered.",
        )

    source = inventory.discovered_sources[0]
    source_pk = _first(PREFERRED_ID_COLUMNS, inventory.identity_columns)
    taxon_pk = _first(PREFERRED_TAXON_COLUMNS, inventory.taxon_key_columns)
    if source_pk is None:
        return ProjectionPlan(
            domain=inventory.domain, source=source, state="blocked", sql=None,
            source_pk_column=None, taxon_pk_column=taxon_pk,
            limitation="No stable record identity column was discovered.",
        )
    if taxon_pk is None:
        return ProjectionPlan(
            domain=inventory.domain, source=source, state="blocked", sql=None,
            source_pk_column=source_pk, taxon_pk_column=None,
            limitation="No canonical taxon identifier was discovered; crosswalk or curated resolver required.",
        )

    # Relation and column names originate from the fixed catalog inventory, not
    # request input. The graph-backbone EXISTS clause prevents orphan endpoints.
    sql = (
        f"SELECT s.{source_pk} AS source_pk, s.{taxon_pk} AS taxon_pk, "
        f"to_jsonb(s) AS source_payload FROM {source} s "
        f"WHERE s.{source_pk} IS NOT NULL AND s.{taxon_pk} IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM oc_graph.kg_nodes k "
        f"WHERE k.node_type='taxon' AND k.source_pk=s.{taxon_pk}::text)"
    )
    assert_safe_sql(sql)
    return ProjectionPlan(
        domain=inventory.domain, source=source, state="ready", sql=sql,
        source_pk_column=source_pk, taxon_pk_column=taxon_pk,
    )


def build_projection_report(inventories: Iterable[DomainInventory]) -> dict:
    plans = [build_projection(item) for item in inventories]
    return {
        "contract": "calyx-dynamic-source-projection-v1",
        "plans": [
            {
                "domain": p.domain,
                "source": p.source,
                "state": p.state,
                "executable": p.executable,
                "source_pk_column": p.source_pk_column,
                "taxon_pk_column": p.taxon_pk_column,
                "limitation": p.limitation,
            }
            for p in plans
        ],
        "ready_domains": [p.domain for p in plans if p.executable],
        "blocked_domains": [p.domain for p in plans if p.state == "blocked"],
        "unavailable_domains": [p.domain for p in plans if p.state == "unavailable"],
        "withheld_domains": [p.domain for p in plans if p.state == "withheld"],
        "fully_projectable": all(
            p.executable or p.state == "withheld" for p in plans
        ),
    }
