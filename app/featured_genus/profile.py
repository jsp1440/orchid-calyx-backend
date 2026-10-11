"""Featured Genus profile composer — featured-genus-profile/v1.

Composes one coherent, evidence-stated genus payload from existing canonical
Calyx sources:

  * taxonomy   — public.orchid_taxonomy (accepted genus resolution, recorded
                 species-name count, representative recorded names);
  * media      — the shared approved-media selection from
                 app.routers.orchid_widgets (identical policy to the live
                 /api/media/genus endpoint);
  * habitat    — oc_widget.v_genus_of_day_cards (climate/collection tags,
                 elevation range) where a card exists;
  * graph      — oc_graph via runtime.knowledge_graph traversal, the same
                 service behind /api/knowledge-graph/genus/{genus}.

Evidence-state discipline (binding):
  * "known"       — a canonical source returned linked evidence;
  * "unknown"     — the source answered and holds nothing linked here yet.
                    Unknown is never reported as zero or biological absence;
  * "unavailable" — the source did not answer. No fallback claim is
                    substituted in either direction.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import text

from app.database import get_engine
from app.featured_genus import FEATURED_GENUS_PROFILE_CONTRACT
from app.routers.orchid_widgets import query_approved_genus_media

EVIDENCE_STATES = ("known", "unknown", "unavailable")

GRAPH_DOMAINS: tuple[str, ...] = (
    "taxonomy",
    "media",
    "occurrences",
    "traits",
    "literature",
    "pollinators",
    "conservation",
    "geography",
    "habitat",
    "climate",
    "elevation",
    "mycorrhiza",
)

TAXONOMY_EXISTS_SQL = text("""
    SELECT 1
    FROM public.orchid_taxonomy
    WHERE lower(genus) = lower(:genus)
    LIMIT 1
""")

TAXONOMY_COUNT_SQL = text("""
    SELECT COUNT(DISTINCT scientific_name) AS recorded_names
    FROM public.orchid_taxonomy
    WHERE lower(genus) = lower(:genus)
""")

TAXONOMY_SAMPLE_SQL = text("""
    SELECT DISTINCT scientific_name
    FROM public.orchid_taxonomy
    WHERE lower(genus) = lower(:genus)
    ORDER BY scientific_name ASC
    LIMIT :limit
""")

WIDGET_CARD_SQL = text("""
    SELECT genus, taxonomy_id, accepted_scientific_name, species, hero_image,
           image_count, climate_tag, collection_tag, min_elevation, max_elevation
    FROM oc_widget.v_genus_of_day_cards
    WHERE lower(genus) = lower(:genus)
    LIMIT 1
""")

PROFILE_NOTES = (
    "Unknown means no evidence is currently linked in the Continuum; it is never a claim of biological absence.",
    "Unavailable means an evidence service did not answer; no fallback scientific claim is substituted.",
    "Recorded species counts come from canonical taxonomy rows, not a global monographic census.",
)


def _number_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _load_taxonomy(conn: Any, genus: str, *, sample_limit: int = 12) -> dict[str, Any]:
    exists = conn.execute(TAXONOMY_EXISTS_SQL, {"genus": genus}).first()
    if not exists:
        return {"state": "known", "exists": False, "recorded_species_count": None, "representative_names": []}
    count_row = conn.execute(TAXONOMY_COUNT_SQL, {"genus": genus}).mappings().first() or {}
    sample_rows = conn.execute(
        TAXONOMY_SAMPLE_SQL, {"genus": genus, "limit": sample_limit}
    ).mappings().all()
    return {
        "state": "known",
        "exists": True,
        "recorded_species_count": _number_or_none(count_row.get("recorded_names")),
        "representative_names": [
            str(row["scientific_name"]) for row in sample_rows if row.get("scientific_name")
        ],
    }


def _load_widget_card(conn: Any, genus: str) -> dict[str, Any]:
    """Habitat/elevation evidence from the widget card view.

    A missing row is `unknown` (no card recorded for this genus), never a
    zero-elevation or no-habitat claim. A query error is `unavailable`.
    """
    try:
        row = conn.execute(WIDGET_CARD_SQL, {"genus": genus}).mappings().first()
    except Exception:
        return {"state": "unavailable"}
    if not row:
        return {"state": "unknown"}
    return {
        "state": "known",
        "climate_tag": row.get("climate_tag") or None,
        "collection_tag": row.get("collection_tag") or None,
        "min_elevation_m": _number_or_none(row.get("min_elevation")),
        "max_elevation_m": _number_or_none(row.get("max_elevation")),
        "recorded_exemplar": row.get("accepted_scientific_name") or None,
        "recorded_image_count": _number_or_none(row.get("image_count")),
        "source": "oc_widget.v_genus_of_day_cards",
    }


def load_graph_coverage(genus: str) -> tuple[str, dict[str, Any] | None]:
    """Best-effort Knowledge Graph coverage through the existing traversal.

    Returns ("ok", payload) when the genus resolves and traverses, ("unknown",
    None) when the graph answered but holds no focal genus node, and
    ("unavailable", None) whenever the graph cannot answer. This function
    never fabricates coverage.
    """
    try:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            return "unavailable", None
        from runtime.knowledge_graph import PostgresGraphRepository, traverse

        repo = PostgresGraphRepository(dsn)
        node = repo.find_genus_node(genus)
        if node is None:
            return "unknown", None
        payload = traverse(repo, node, depth=2, limit=500, offset=0)
        if not isinstance(payload, dict):
            return "unavailable", None
        return "ok", payload
    except Exception:
        return "unavailable", None


def _domain_subrecord(graph_state: str, coverage: dict[str, Any] | None, domain: str) -> dict[str, Any]:
    if graph_state == "unavailable":
        return {"state": "unavailable", "linked_nodes": None, "linked_edges": None}
    if graph_state != "ok" or not isinstance(coverage, dict):
        return {"state": "unknown", "linked_nodes": None, "linked_edges": None}
    entry = coverage.get(domain)
    if not isinstance(entry, dict):
        return {"state": "unknown", "linked_nodes": None, "linked_edges": None}
    nodes = _number_or_none(entry.get("nodes"))
    edges = _number_or_none(entry.get("edges"))
    known = bool((nodes or 0) > 0 or (edges or 0) > 0)
    return {
        "state": "known" if known else "unknown",
        "linked_nodes": nodes,
        "linked_edges": edges,
    }


def invalid_genus_profile(requested_genus: str, *, generated_at: str) -> dict[str, Any]:
    return {
        "contract": FEATURED_GENUS_PROFILE_CONTRACT,
        "status": "invalid_genus",
        "requested_genus": requested_genus,
        "accepted_genus": None,
        "generated_at": generated_at,
        "notes": [
            "The requested name is not an accepted genus in canonical Orchid Continuum taxonomy.",
            *PROFILE_NOTES,
        ],
    }


def build_featured_genus_profile(
    genus: str,
    *,
    requested_genus: str | None = None,
    media_limit: int = 12,
    graph_loader: Callable[[str], tuple[str, dict[str, Any] | None]] = load_graph_coverage,
) -> dict[str, Any]:
    """Compose the featured-genus-profile/v1 payload for an accepted genus.

    Taxonomy is the acceptance gate: if it cannot answer, the profile fails
    closed with 503 rather than guessing. Media, habitat, and graph evidence
    degrade individually to `unavailable` so one cold service never empties
    the whole exhibit.
    """
    requested = requested_genus if requested_genus is not None else genus
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        with get_engine().connect() as conn:
            taxonomy = _load_taxonomy(conn, genus)
            if not taxonomy.get("exists"):
                return invalid_genus_profile(requested, generated_at=generated_at)
            habitat = _load_widget_card(conn, genus)
            try:
                media_selection = query_approved_genus_media(conn, genus, limit=media_limit)
                media_items = media_selection["items"]
                media = {
                    "state": "known" if media_items else "unknown",
                    "status": "ok" if media_items else "no_approved_media",
                    "returned_count": len(media_items),
                    "items": media_items,
                    "exclusion_counts": media_selection["exclusion_counts"],
                }
            except Exception:
                media = {
                    "state": "unavailable",
                    "status": "service_error",
                    "returned_count": None,
                    "items": [],
                    "exclusion_counts": None,
                }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Canonical taxonomy is unavailable; the featured genus profile fails closed.",
        ) from exc

    graph_state, graph_payload = graph_loader(genus)
    coverage = None
    graph_block: dict[str, Any] = {"state": "unknown" if graph_state == "unknown" else graph_state}
    if graph_state == "ok" and isinstance(graph_payload, dict):
        graph = graph_payload.get("graph") if isinstance(graph_payload.get("graph"), dict) else {}
        coverage = graph_payload.get("domain_coverage")
        graph_block.update(
            {
                "state": "known",
                "node_count": _number_or_none(graph.get("node_count")),
                "edge_count": _number_or_none(graph.get("edge_count")),
                "focal_node": graph_payload.get("focal_node")
                if isinstance(graph_payload.get("focal_node"), dict)
                else None,
                "truncated": graph_payload.get("pagination", {}).get("truncated")
                if isinstance(graph_payload.get("pagination"), dict)
                else None,
            }
        )
    else:
        graph_block.update(
            {"node_count": None, "edge_count": None, "focal_node": None, "truncated": None}
        )

    domains = {domain: _domain_subrecord(graph_state, coverage, domain) for domain in GRAPH_DOMAINS}
    gaps = sorted(domain for domain, record in domains.items() if record["state"] == "unknown")

    return {
        "contract": FEATURED_GENUS_PROFILE_CONTRACT,
        "status": "ok",
        "requested_genus": requested,
        "accepted_genus": genus,
        "generated_at": generated_at,
        "taxonomy": {
            "state": taxonomy["state"],
            "accepted_genus": genus,
            "recorded_species_count": taxonomy["recorded_species_count"],
            "recorded_species_count_scope": (
                "Distinct recorded species names in public.orchid_taxonomy; "
                "a recorded count, not a global monographic census."
            ),
            "representative_names": taxonomy["representative_names"],
        },
        "media": media,
        "habitat": habitat,
        "knowledge_graph": graph_block,
        "domains": domains,
        "gaps": gaps,
        "provenance": {
            "taxonomy_source": "public.orchid_taxonomy",
            "media_source": "public.orchid_images via the approved Featured Genus selection policy",
            "habitat_source": "oc_widget.v_genus_of_day_cards",
            "graph_source": "oc_graph.kg_nodes / oc_graph.kg_edges via runtime.knowledge_graph traversal",
        },
        "notes": list(PROFILE_NOTES),
    }
