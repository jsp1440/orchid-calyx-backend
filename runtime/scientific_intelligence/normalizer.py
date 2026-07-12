"""BUILD-062 normalization layer for scientific intelligence payloads.

Every adapter produces a raw dict; this module converts raw dicts into
normalized domain objects that the aggregator and intelligence layers can
consume without knowing adapter-specific field names.

Normalization contract:
- Every output has a ``subsystem_id``, ``name``, ``status``, and ``available`` flag.
- Numeric fields are always int or float (never None where a numeric is expected).
- Timestamps are ISO-8601 strings or the sentinel "unavailable".
- Provenance is preserved in a ``provenance`` sub-dict.
"""

from __future__ import annotations

from typing import Any

from runtime.scientific_intelligence.utils import to_int, to_float, utc_now


def _status(available: bool, count: int, threshold: int = 1) -> str:
    """Derive a human-readable status string from availability and record count.

    Args:
        available: Whether the subsystem's source table was reachable.
        count: Total record count from the source table.
        threshold: Minimum count required to be considered 'live' (default: 1).

    Returns:
        'unavailable' if the source table is unreachable,
        'live'        if count >= threshold (records exist and are accessible),
        'empty'       if the table is reachable but contains no records.
    """
    if not available:
        return "unavailable"
    if count >= threshold:
        return "live"
    return "empty"


def normalize_knowledge_graph(raw: dict[str, Any]) -> dict[str, Any]:
    entities = to_int(raw.get("entities"))
    relationships = to_int(raw.get("relationships"))
    disconnected = to_int(raw.get("disconnected_nodes"))
    validation_pct = to_float(raw.get("validation_pct"), 0.0)
    growth_rate = to_float(raw.get("growth_rate"), 0.0)
    available = bool(raw.get("available"))
    return {
        "subsystem_id": "knowledge_graph",
        "name": "Knowledge Graph",
        "available": available,
        "status": _status(available, entities + relationships),
        "entities": entities,
        "relationships": relationships,
        "disconnected_nodes": disconnected,
        "validation_pct": validation_pct,
        "growth_rate": growth_rate,
        "last_sync": raw.get("last_sync", "unavailable"),
        "provenance": raw.get("provenance", {}),
        "generated_at": raw.get("generated_at", utc_now()),
    }


def normalize_atlas(raw: dict[str, Any]) -> dict[str, Any]:
    occurrences = to_int(raw.get("occurrences"))
    taxa_covered = to_int(raw.get("taxa_covered"))
    available = bool(raw.get("available"))
    return {
        "subsystem_id": "atlas",
        "name": "Atlas",
        "available": available,
        "status": _status(available, occurrences),
        "occurrences": occurrences,
        "taxa_covered": taxa_covered,
        "coordinate_coverage_pct": to_float(raw.get("coordinate_coverage_pct")),
        "last_import": raw.get("last_import", "unavailable"),
        "provenance": raw.get("provenance", {}),
        "generated_at": raw.get("generated_at", utc_now()),
    }


def normalize_literature(raw: dict[str, Any]) -> dict[str, Any]:
    documents = to_int(raw.get("documents"))
    extracted_relationships = to_int(raw.get("extracted_relationships"))
    available = bool(raw.get("available"))
    return {
        "subsystem_id": "literature",
        "name": "Literature",
        "available": available,
        "status": _status(available, documents),
        "documents": documents,
        "extracted_relationships": extracted_relationships,
        "ingestion_rate": to_float(raw.get("ingestion_rate")),
        "last_ingestion": raw.get("last_ingestion", "unavailable"),
        "provenance": raw.get("provenance", {}),
        "generated_at": raw.get("generated_at", utc_now()),
    }


def normalize_pollinators(raw: dict[str, Any]) -> dict[str, Any]:
    relationships = to_int(raw.get("relationships"))
    taxa_covered = to_int(raw.get("taxa_covered"))
    available = bool(raw.get("available"))
    return {
        "subsystem_id": "pollinators",
        "name": "Pollinators",
        "available": available,
        "status": _status(available, relationships),
        "relationships": relationships,
        "taxa_covered": taxa_covered,
        "coverage_pct": to_float(raw.get("coverage_pct")),
        "last_harvest": raw.get("last_harvest", "unavailable"),
        "provenance": raw.get("provenance", {}),
        "generated_at": raw.get("generated_at", utc_now()),
    }


def normalize_mycorrhiza(raw: dict[str, Any]) -> dict[str, Any]:
    records = to_int(raw.get("records"))
    taxa_covered = to_int(raw.get("taxa_covered"))
    available = bool(raw.get("available"))
    return {
        "subsystem_id": "mycorrhiza",
        "name": "Mycorrhiza",
        "available": available,
        "status": _status(available, records),
        "records": records,
        "taxa_covered": taxa_covered,
        "coverage_pct": to_float(raw.get("coverage_pct")),
        "last_harvest": raw.get("last_harvest", "unavailable"),
        "provenance": raw.get("provenance", {}),
        "generated_at": raw.get("generated_at", utc_now()),
    }


def normalize_vision(raw: dict[str, Any]) -> dict[str, Any]:
    images = to_int(raw.get("images"))
    taxa_with_images = to_int(raw.get("taxa_with_images"))
    available = bool(raw.get("available"))
    return {
        "subsystem_id": "vision",
        "name": "Vision Lab",
        "available": available,
        "status": _status(available, images),
        "images": images,
        "taxa_with_images": taxa_with_images,
        "quality_score": to_float(raw.get("quality_score")),
        "last_harvest": raw.get("last_harvest", "unavailable"),
        "provenance": raw.get("provenance", {}),
        "generated_at": raw.get("generated_at", utc_now()),
    }


def normalize_grant_office(raw: dict[str, Any]) -> dict[str, Any]:
    opportunities = to_int(raw.get("opportunities"))
    active_grants = to_int(raw.get("active_grants"))
    available = bool(raw.get("available"))
    return {
        "subsystem_id": "grant_office",
        "name": "Grant Office",
        "available": available,
        "status": _status(available, opportunities + active_grants),
        "opportunities": opportunities,
        "active_grants": active_grants,
        "nearest_deadline": raw.get("nearest_deadline", "unavailable"),
        "recommended_publications": to_int(raw.get("recommended_publications")),
        "provenance": raw.get("provenance", {}),
        "generated_at": raw.get("generated_at", utc_now()),
    }


# Map subsystem IDs to their normalizer functions.
_NORMALIZERS = {
    "knowledge_graph": normalize_knowledge_graph,
    "atlas": normalize_atlas,
    "literature": normalize_literature,
    "pollinators": normalize_pollinators,
    "mycorrhiza": normalize_mycorrhiza,
    "vision": normalize_vision,
    "grant_office": normalize_grant_office,
}


def normalize(subsystem_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw adapter payload using the registered normalizer."""
    normalizer = _NORMALIZERS.get(subsystem_id)
    if normalizer is None:
        return {
            "subsystem_id": subsystem_id,
            "available": False,
            "status": "unknown",
            "error": f"No normalizer registered for subsystem '{subsystem_id}'",
            "generated_at": utc_now(),
        }
    return normalizer(raw)
