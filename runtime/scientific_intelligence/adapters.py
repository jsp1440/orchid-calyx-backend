"""BUILD-062 live subsystem adapters for Scientific Intelligence.

Each adapter:
- Tries to connect to the Calyx database using the same DATABASE_URL
  environment variable used throughout the backend.
- Normalizes the raw payload via runtime.scientific_intelligence.normalizer.
- Falls back gracefully when the database is unreachable or a table does not
  exist — returning an ``available=False`` payload rather than raising.
- Is cached for DEFAULT_TTL seconds to avoid excessive DB round-trips.

Adapters are intentionally read-only and never write to the database.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable

import psycopg
from psycopg import sql as psycopg_sql

from runtime.scientific_intelligence.cache import get_cached, set_cached
from runtime.scientific_intelligence.normalizer import normalize
from runtime.scientific_intelligence.utils import utc_now

DATABASE_URL: str | None = os.environ.get("DATABASE_URL")
ADAPTER_CACHE_TTL: int = 60  # seconds


def _fallback(subsystem_id: str, reason: str) -> dict[str, Any]:
    """Return a normalized unavailable payload."""
    return normalize(subsystem_id, {
        "available": False,
        "provenance": {"source": "fallback", "reason": reason},
        "generated_at": utc_now(),
    })


def _with_db(callback: Callable[[Any], dict[str, Any]], subsystem_id: str) -> dict[str, Any]:
    """Connect to the database, run *callback(cursor)*, and return the result.

    Falls back to an unavailable payload if the database is not configured or
    a connection error occurs.
    """
    if not DATABASE_URL:
        return _fallback(subsystem_id, "DATABASE_URL not configured")
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                return callback(cur)
    except Exception as exc:  # pragma: no cover - exercised in deployed runtime
        return _fallback(subsystem_id, f"Database unavailable: {exc}")


def _table_exists(cur: Any, fq_table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (fq_table,))
    return cur.fetchone()[0] is not None


def _safe_count(cur: Any, fq_table: str) -> int | None:
    """Return row count for *fq_table* or None if the table does not exist.

    Table identity is composed using psycopg.sql.Identifier so that the table
    name is never interpolated directly into the query string.  The table name
    comes exclusively from the hardcoded candidate lists in this module, so
    there is no external input, but using the safe composition API is good
    practice and prevents accidental issues if the list is extended.
    """
    if not _table_exists(cur, fq_table):
        return None
    # Split "schema.table" into its parts for safe identifier composition.
    parts = fq_table.split(".", 1)
    if len(parts) == 2:
        query = psycopg_sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            psycopg_sql.Identifier(parts[0]),
            psycopg_sql.Identifier(parts[1]),
        )
    else:
        query = psycopg_sql.SQL("SELECT COUNT(*) FROM {}").format(
            psycopg_sql.Identifier(parts[0]),
        )
    cur.execute(query)
    return int(cur.fetchone()[0])


def _first_count(cur: Any, candidates: Iterable[str]) -> tuple[str | None, int]:
    """Return the first reachable table and its row count."""
    for table in candidates:
        count = _safe_count(cur, table)
        if count is not None:
            return table, count
    return None, 0


def _coverage_pct(numerator: int, denominator: int) -> float:
    """Calculate coverage percentage as a 0.0–100.0 float.

    Returns 0.0 when *denominator* is zero to avoid division-by-zero errors.
    The result is capped at 100.0 in case source counts produce a ratio > 1.
    """
    if denominator <= 0:
        return 0.0
    return min(100.0, round(numerator / denominator * 100, 1))


# ---------------------------------------------------------------------------
# Knowledge Graph adapter
# ---------------------------------------------------------------------------

_KG_ENTITY_CANDIDATES = [
    "oc_graph.nodes",
    "oc_graph.entities",
    "oc_graph.taxa",
    "oc_relationships.entities",
    "public.graph_nodes",
]

_KG_RELATIONSHIP_CANDIDATES = [
    "oc_graph.edges",
    "oc_graph.relationships",
    "oc_relationships.relationships",
    "oc_literature.extracted_relationships",
    "public.relationships",
]


def _fetch_knowledge_graph(cur: Any) -> dict[str, Any]:
    entity_table, entities = _first_count(cur, _KG_ENTITY_CANDIDATES)
    rel_table, relationships = _first_count(cur, _KG_RELATIONSHIP_CANDIDATES)

    available = entity_table is not None or rel_table is not None
    provenance = {}
    if entity_table:
        provenance["entity_table"] = entity_table
    if rel_table:
        provenance["relationship_table"] = rel_table

    return normalize("knowledge_graph", {
        "available": available,
        "entities": entities,
        "relationships": relationships,
        "disconnected_nodes": 0,
        "validation_pct": 0.0,
        "growth_rate": 0.0,
        "last_sync": utc_now() if available else "unavailable",
        "provenance": provenance,
        "generated_at": utc_now(),
    })


def knowledge_graph_adapter() -> dict[str, Any]:
    cached = get_cached("knowledge_graph", ADAPTER_CACHE_TTL)
    if cached is not None:
        return cached
    result = _with_db(_fetch_knowledge_graph, "knowledge_graph")
    set_cached("knowledge_graph", result)
    return result


# ---------------------------------------------------------------------------
# Atlas adapter
# ---------------------------------------------------------------------------

_ATLAS_CANDIDATES = [
    "oc_atlas.occurrences",
    "oc_atlas.map_data",
    "public.orchid_occurrences",
    "public.occurrences",
    "public.map_data",
]

_TAXONOMY_CANDIDATES = [
    "oc_taxonomy.taxa",
    "oc_taxonomy.orchid_taxa",
    "public.orchid_taxa",
    "public.orchid_species",
    "public.taxonomy",
]


def _fetch_atlas(cur: Any) -> dict[str, Any]:
    occ_table, occurrences = _first_count(cur, _ATLAS_CANDIDATES)
    tax_table, taxa = _first_count(cur, _TAXONOMY_CANDIDATES)
    available = occ_table is not None
    provenance: dict[str, Any] = {}
    if occ_table:
        provenance["occurrence_table"] = occ_table
    if tax_table:
        provenance["taxonomy_table"] = tax_table
    taxa_covered = taxa if tax_table else 0
    coord_pct = _coverage_pct(occurrences, taxa_covered) if available else 0.0
    return normalize("atlas", {
        "available": available,
        "occurrences": occurrences,
        "taxa_covered": taxa_covered,
        "coordinate_coverage_pct": coord_pct,
        "last_import": utc_now() if available else "unavailable",
        "provenance": provenance,
        "generated_at": utc_now(),
    })


def atlas_adapter() -> dict[str, Any]:
    cached = get_cached("atlas", ADAPTER_CACHE_TTL)
    if cached is not None:
        return cached
    result = _with_db(_fetch_atlas, "atlas")
    set_cached("atlas", result)
    return result


# ---------------------------------------------------------------------------
# Literature adapter
# ---------------------------------------------------------------------------

_LIT_DOC_CANDIDATES = [
    "oc_literature.documents",
    "oc_literature.literature_documents",
    "oc_literature.papers",
    "public.literature_documents",
]

_LIT_REL_CANDIDATES = [
    "oc_literature.extracted_relationships",
    "oc_literature.relationships",
    "public.literature_relationships",
]


def _fetch_literature(cur: Any) -> dict[str, Any]:
    doc_table, documents = _first_count(cur, _LIT_DOC_CANDIDATES)
    rel_table, extracted = _first_count(cur, _LIT_REL_CANDIDATES)
    available = doc_table is not None
    provenance: dict[str, Any] = {}
    if doc_table:
        provenance["document_table"] = doc_table
    if rel_table:
        provenance["relationship_table"] = rel_table
    return normalize("literature", {
        "available": available,
        "documents": documents,
        "extracted_relationships": extracted,
        "ingestion_rate": 0.0,
        "last_ingestion": utc_now() if available else "unavailable",
        "provenance": provenance,
        "generated_at": utc_now(),
    })


def literature_adapter() -> dict[str, Any]:
    cached = get_cached("literature", ADAPTER_CACHE_TTL)
    if cached is not None:
        return cached
    result = _with_db(_fetch_literature, "literature")
    set_cached("literature", result)
    return result


# ---------------------------------------------------------------------------
# Pollinators adapter
# ---------------------------------------------------------------------------

_POLLINATOR_CANDIDATES = [
    "oc_pollination.relationships",
    "oc_interactions.relationships",
    "oc_relationships.relationships",
    "public.pollinator_relationships",
    "public.relationships",
]


def _fetch_pollinators(cur: Any) -> dict[str, Any]:
    rel_table, relationships = _first_count(cur, _POLLINATOR_CANDIDATES)
    tax_table, taxa = _first_count(cur, _TAXONOMY_CANDIDATES)
    available = rel_table is not None
    provenance: dict[str, Any] = {}
    if rel_table:
        provenance["relationship_table"] = rel_table
    taxa_covered = min(relationships, taxa) if available and taxa > 0 else 0
    coverage_pct = _coverage_pct(taxa_covered, taxa) if available else 0.0
    return normalize("pollinators", {
        "available": available,
        "relationships": relationships,
        "taxa_covered": taxa_covered,
        "coverage_pct": coverage_pct,
        "last_harvest": utc_now() if available else "unavailable",
        "provenance": provenance,
        "generated_at": utc_now(),
    })


def pollinators_adapter() -> dict[str, Any]:
    cached = get_cached("pollinators", ADAPTER_CACHE_TTL)
    if cached is not None:
        return cached
    result = _with_db(_fetch_pollinators, "pollinators")
    set_cached("pollinators", result)
    return result


# ---------------------------------------------------------------------------
# Mycorrhiza adapter
# ---------------------------------------------------------------------------

_MYCORRHIZA_CANDIDATES = [
    "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
    "oc_mycorrhiza.relationships",
    "public.mycorrhiza_relationships",
]


def _fetch_mycorrhiza(cur: Any) -> dict[str, Any]:
    myco_table, records = _first_count(cur, _MYCORRHIZA_CANDIDATES)
    tax_table, taxa = _first_count(cur, _TAXONOMY_CANDIDATES)
    available = myco_table is not None
    provenance: dict[str, Any] = {}
    if myco_table:
        provenance["mycorrhiza_table"] = myco_table
    taxa_covered = min(records, taxa) if available and taxa > 0 else 0
    coverage_pct = _coverage_pct(taxa_covered, taxa) if available else 0.0
    return normalize("mycorrhiza", {
        "available": available,
        "records": records,
        "taxa_covered": taxa_covered,
        "coverage_pct": coverage_pct,
        "last_harvest": utc_now() if available else "unavailable",
        "provenance": provenance,
        "generated_at": utc_now(),
    })


def mycorrhiza_adapter() -> dict[str, Any]:
    cached = get_cached("mycorrhiza", ADAPTER_CACHE_TTL)
    if cached is not None:
        return cached
    result = _with_db(_fetch_mycorrhiza, "mycorrhiza")
    set_cached("mycorrhiza", result)
    return result


# ---------------------------------------------------------------------------
# Vision adapter
# ---------------------------------------------------------------------------

_VISION_CANDIDATES = [
    "public.orchid_images_linked_v2",
    "public.orchid_images",
    "public.record_media_link",
    "oc_media.orchid_images",
    "oc_media.images",
]


def _fetch_vision(cur: Any) -> dict[str, Any]:
    img_table, images = _first_count(cur, _VISION_CANDIDATES)
    tax_table, taxa = _first_count(cur, _TAXONOMY_CANDIDATES)
    available = img_table is not None
    provenance: dict[str, Any] = {}
    if img_table:
        provenance["image_table"] = img_table
    taxa_with_images = min(images, taxa) if available and taxa > 0 else 0
    quality_score = min(100.0, _coverage_pct(images, max(taxa, 1)) * 0.2) if available else 0.0
    return normalize("vision", {
        "available": available,
        "images": images,
        "taxa_with_images": taxa_with_images,
        "quality_score": quality_score,
        "last_harvest": utc_now() if available else "unavailable",
        "provenance": provenance,
        "generated_at": utc_now(),
    })


def vision_adapter() -> dict[str, Any]:
    cached = get_cached("vision", ADAPTER_CACHE_TTL)
    if cached is not None:
        return cached
    result = _with_db(_fetch_vision, "vision")
    set_cached("vision", result)
    return result


# ---------------------------------------------------------------------------
# Grant Office adapter
# ---------------------------------------------------------------------------
# The Grant Office does not have its own database table yet.  It derives
# intelligence from the state of other subsystems (literature, knowledge_graph,
# pollinators) and exposes a structured payload for Mission Control.


def grant_office_adapter(
    kg: dict[str, Any] | None = None,
    literature: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cached = get_cached("grant_office", ADAPTER_CACHE_TTL)
    if cached is not None:
        return cached

    kg = kg or {}
    literature = literature or {}

    kg_relationships = int(kg.get("relationships", 0))
    lit_documents = int(literature.get("documents", 0))

    # Derive rough opportunity count from data maturity
    opportunities = 0
    if kg_relationships >= 1000:
        opportunities += 2
    if lit_documents >= 100:
        opportunities += 2
    if kg_relationships >= 10000:
        opportunities += 1
    if lit_documents >= 1000:
        opportunities += 1

    active_grants = min(opportunities, 2)

    result = normalize("grant_office", {
        "available": True,
        "opportunities": opportunities,
        "active_grants": active_grants,
        "nearest_deadline": "unavailable",
        "recommended_publications": max(0, lit_documents // 500),
        "provenance": {
            "source": "derived",
            "inputs": ["knowledge_graph", "literature"],
            "kg_relationships": kg_relationships,
            "lit_documents": lit_documents,
        },
        "generated_at": utc_now(),
    })
    set_cached("grant_office", result)
    return result


# ---------------------------------------------------------------------------
# Convenience: fetch all adapters at once
# ---------------------------------------------------------------------------


def fetch_all_adapters() -> dict[str, dict[str, Any]]:
    """Fetch all subsystem adapters and return a keyed dict.

    Each adapter is called independently so that a single failure does not
    block the others.
    """
    kg = knowledge_graph_adapter()
    atlas = atlas_adapter()
    literature = literature_adapter()
    pollinators = pollinators_adapter()
    mycorrhiza = mycorrhiza_adapter()
    vision = vision_adapter()
    grant = grant_office_adapter(kg=kg, literature=literature)
    return {
        "knowledge_graph": kg,
        "atlas": atlas,
        "literature": literature,
        "pollinators": pollinators,
        "mycorrhiza": mycorrhiza,
        "vision": vision,
        "grant_office": grant,
    }
