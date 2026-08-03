"""Full-domain Knowledge Graph integration inventory and publication planning.

This module is deliberately split into two phases:

1. read-only discovery/inventory of every production scientific domain;
2. an explicit publication plan that may be executed only by an owner-authorized
   graph publication command.

Importing or calling ``inventory_full_graph`` performs no writes.  The result is
suitable for Mission Control, Calyx planning, and pre-publication validation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .domain_sources import DOMAIN_SOURCES, DomainSource


@dataclass(frozen=True)
class SourceCandidate:
    schema: str
    table: str

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


@dataclass(frozen=True)
class DomainInventory:
    domain: str
    configured_status: str
    configured_source: str | None
    discovered_sources: tuple[str, ...]
    state: str
    row_count: int | None
    taxon_key_columns: tuple[str, ...]
    identity_columns: tuple[str, ...]
    node_type: str | None
    edge_type: str | None
    limitation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


TAXON_KEY_CANDIDATES = (
    "taxonomy_id",
    "taxon_id",
    "accepted_taxon_id",
    "canonical_taxon_id",
    "orchid_taxonomy_id",
    "taxon_key",
)

IDENTITY_CANDIDATES = (
    "id",
    "record_id",
    "occurrence_id",
    "image_id",
    "media_id",
    "publication_id",
    "trait_id",
    "assessment_id",
    "interaction_id",
    "evidence_id",
)

# Ordered candidates are intentionally conservative.  The live catalog decides
# which source exists; absent sources remain unavailable rather than becoming 0.
DOMAIN_TABLE_CANDIDATES: dict[str, tuple[SourceCandidate, ...]] = {
    "media": (
        SourceCandidate("public", "orchid_images"),
        SourceCandidate("oc_core", "media_assets"),
        SourceCandidate("oc_core", "record_media_link"),
    ),
    "occurrences": (
        SourceCandidate("oc_atlas", "occurrences"),
        SourceCandidate("oc_views", "occurrences_enriched"),
        SourceCandidate("public", "orchid_occurrences"),
    ),
    "geography": (
        SourceCandidate("oc_geo", "places"),
        SourceCandidate("oc_regions", "regions"),
    ),
    "habitat": (
        SourceCandidate("oc_habitat", "taxon_habitat"),
        SourceCandidate("oc_habitat", "habitats"),
    ),
    "climate": (
        SourceCandidate("oc_env", "taxon_climate"),
        SourceCandidate("oc_env_intel", "taxon_climate_summary"),
    ),
    "elevation": (
        SourceCandidate("oc_env", "taxon_elevation"),
        SourceCandidate("oc_dependency", "elevation_derivation_queue"),
    ),
    "traits": (
        SourceCandidate("oc_views", "trait_resolved_v4"),
        SourceCandidate("oc_traits", "traits"),
    ),
    "glossary": (
        SourceCandidate("oc_glossary", "terms"),
        SourceCandidate("oc_zoo", "glossary_terms"),
    ),
    "literature": (
        SourceCandidate("oc_citations", "canonical_taxon_literature_edges"),
        SourceCandidate("oc_citations", "literature_nodes"),
        SourceCandidate("oc_graph", "taxon_literature_edges"),
    ),
    "evidence": (
        SourceCandidate("oc_claims", "evidence_item"),
        SourceCandidate("oc_claims", "claim_evidence_link"),
    ),
    "pollinators": (
        SourceCandidate("oc_pollination", "interactions"),
        SourceCandidate("oc_globi", "interactions"),
        SourceCandidate("oc_interactions", "taxon_interactions"),
    ),
    "mycorrhiza": (
        SourceCandidate("oc_mycorrhiza", "associations"),
        SourceCandidate("oc_dependency", "fungal_dependency_evidence"),
    ),
    "conservation": (
        SourceCandidate("oc_conservation", "conservation_records"),
    ),
    "molecular": (
        SourceCandidate("oc_phylogeny", "taxon_sequences"),
        SourceCandidate("oc_phylogeny", "relationships"),
    ),
    "education": (
        SourceCandidate("oc_story", "knowledge_objects"),
        SourceCandidate("oc_figures", "figures"),
        SourceCandidate("ocu", "lessons"),
    ),
}


def _table_exists(cur, candidate: SourceCandidate) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (candidate.qualified,))
    row = cur.fetchone()
    return bool(row[0] if not isinstance(row, dict) else next(iter(row.values())))


def _columns(cur, candidate: SourceCandidate) -> tuple[str, ...]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (candidate.schema, candidate.table),
    )
    return tuple(str(r[0] if not isinstance(r, dict) else r["column_name"]) for r in cur.fetchall())


def _count(cur, candidate: SourceCandidate) -> int:
    # Candidate names are constants defined in this module, never user input.
    cur.execute(f"SELECT COUNT(*) FROM {candidate.qualified}")
    row = cur.fetchone()
    return int((row[0] if not isinstance(row, dict) else next(iter(row.values()))) or 0)


def inventory_domain(cur, source: DomainSource) -> DomainInventory:
    if source.status != "production":
        return DomainInventory(
            domain=source.domain,
            configured_status=source.status,
            configured_source=source.source,
            discovered_sources=(),
            state="withheld" if source.status == "staging_only" else "unavailable",
            row_count=None,
            taxon_key_columns=(),
            identity_columns=(),
            node_type=source.node_type,
            edge_type=source.edge_type,
            limitation=source.note or "Domain is not approved as production evidence.",
        )

    if source.domain == "taxonomy":
        candidates = (SourceCandidate("oc_graph", "kg_nodes"), SourceCandidate("oc_graph", "kg_edges"))
    else:
        candidates = DOMAIN_TABLE_CANDIDATES.get(source.domain, ())

    existing = tuple(candidate for candidate in candidates if _table_exists(cur, candidate))
    if not existing:
        return DomainInventory(
            domain=source.domain,
            configured_status=source.status,
            configured_source=source.source,
            discovered_sources=(),
            state="unavailable",
            row_count=None,
            taxon_key_columns=(),
            identity_columns=(),
            node_type=source.node_type,
            edge_type=source.edge_type,
            limitation="No recognized live source table or view was discovered.",
        )

    columns: set[str] = set()
    row_count = 0
    for candidate in existing:
        columns.update(_columns(cur, candidate))
        row_count += _count(cur, candidate)

    taxon_keys = tuple(c for c in TAXON_KEY_CANDIDATES if c in columns)
    identities = tuple(c for c in IDENTITY_CANDIDATES if c in columns)
    state = "available" if source.domain == "taxonomy" or taxon_keys else "partial"
    limitation = None
    if state == "partial":
        limitation = "Source exists but no recognized canonical taxon key was discovered; resolver mapping is required before publication."

    return DomainInventory(
        domain=source.domain,
        configured_status=source.status,
        configured_source=source.source,
        discovered_sources=tuple(c.qualified for c in existing),
        state=state,
        row_count=row_count,
        taxon_key_columns=taxon_keys,
        identity_columns=identities,
        node_type=source.node_type,
        edge_type=source.edge_type,
        limitation=limitation,
    )


def inventory_full_graph(cur) -> dict[str, Any]:
    domains = [inventory_domain(cur, source) for source in DOMAIN_SOURCES]
    blockers = [
        f"{d.domain}:{d.state}"
        for d in domains
        if d.configured_status == "production" and d.state != "available"
    ]
    return {
        "contract": "calyx-full-graph-integration-inventory-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domains": [d.as_dict() for d in domains],
        "production_domains": sum(d.configured_status == "production" for d in domains),
        "available_domains": sum(d.state == "available" for d in domains),
        "partial_domains": sum(d.state == "partial" for d in domains),
        "unavailable_domains": sum(d.state == "unavailable" for d in domains),
        "withheld_domains": sum(d.state == "withheld" for d in domains),
        "blockers": blockers,
        "fully_integrated": not blockers,
        "graph_mutation": False,
        "publication_authorized": False,
    }


def build_publication_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    """Convert an inventory into an explicit, non-executing publication plan."""
    steps: list[dict[str, Any]] = []
    for domain in inventory.get("domains", []):
        state = domain.get("state")
        status = domain.get("configured_status")
        if status != "production":
            continue
        action = "materialize_nodes_and_edges" if state == "available" else "resolve_adapter_blocker"
        steps.append(
            {
                "domain": domain.get("domain"),
                "action": action,
                "sources": domain.get("discovered_sources", []),
                "node_type": domain.get("node_type"),
                "edge_type": domain.get("edge_type"),
                "requires_owner_authorization": action == "materialize_nodes_and_edges",
                "limitation": domain.get("limitation"),
            }
        )
    return {
        "contract": "calyx-full-graph-publication-plan-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_inventory_contract": inventory.get("contract"),
        "steps": steps,
        "executable": False,
        "reason": "Production graph writes require a separately authorized publication run.",
    }
