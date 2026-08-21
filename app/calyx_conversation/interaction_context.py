from __future__ import annotations

from typing import Any

MAX_TRAIL = 8
MAX_TEXT = 240
MAX_QUESTION_TEXT = 4000
MAX_ROUTE_TAXON = 180


def _text(value: Any, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _surface(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = {
        "surface": _text(value.get("surface"), 80),
        "module": _text(value.get("module"), 80),
        "object_type": _text(value.get("object_type"), 80),
        "object_id": _text(value.get("object_id"), 160),
        "label": _text(value.get("label"), 160),
        "path": _text(value.get("path"), 240),
        "observed_at": _text(value.get("observed_at"), 80),
    }
    return {key: item for key, item in result.items() if item is not None}


def _route_context(value: Any) -> dict[str, Any] | None:
    """Preserve bounded navigation context without promoting it to evidence.

    The frontend uses this boundary for Atlas/Featured Genus/Research continuity.
    Client-supplied evidence flags are never trusted: this sanitizer emits the
    scientific-boundary metadata itself and only keeps the exact Research taxon
    when the route explicitly came from Research Station.
    """

    if not isinstance(value, dict):
        return None

    origin = _text(value.get("origin"), 80)
    result: dict[str, Any] = {
        "context_is_evidence": False,
        "context_purpose": "navigation continuity and reference resolution only",
    }
    if origin:
        result["origin"] = origin

    featured = value.get("featured_taxon")
    if isinstance(featured, dict):
        rank = _text(featured.get("rank"), 40)
        accepted_name = _text(featured.get("accepted_name"), 160)
        if rank == "genus" and accepted_name:
            result["featured_taxon"] = {
                "rank": "genus",
                "accepted_name": accepted_name,
                "taxon_is_evidence": False,
            }

    question = _text(value.get("question"), MAX_QUESTION_TEXT)
    if question and value.get("question_source") == "user":
        result["question"] = question
        result["question_source"] = "user"
        result["question_is_evidence"] = False

    taxon = _text(value.get("taxon"), MAX_ROUTE_TAXON)
    if origin == "research-station" and taxon:
        result["taxon"] = taxon
        result["taxon_source"] = "research-station"
        result["taxon_is_evidence"] = False

    return result if len(result) > 2 else None


def sanitize_interaction_context(value: Any) -> dict[str, Any]:
    """Return bounded UI/session context for conversational reference resolution.

    The current user question and safe route handoff are preserved as continuity
    metadata so synthesis remains question- and subject-centered even when a
    Brain mission is not launched. They are explicitly non-evidentiary and
    cannot be promoted into scientific knowledge.
    """
    source = value if isinstance(value, dict) else {}
    current = _surface(source.get("current_surface"))
    route = _route_context(source.get("route_context"))
    raw_trail = source.get("session_trail")
    trail: list[dict[str, Any]] = []
    if isinstance(raw_trail, list):
        for item in raw_trail[-MAX_TRAIL:]:
            surface = _surface(item)
            if surface:
                trail.append(surface)

    result: dict[str, Any] = {
        "context_is_evidence": False,
        "context_purpose": "interaction continuity and reference resolution only",
    }
    for key, limit in (
        ("surface", 100),
        ("concept", 160),
        ("current_concept_label", 160),
        ("current_question", MAX_QUESTION_TEXT),
    ):
        item = _text(source.get(key), limit)
        if item:
            result[key] = item
    if current:
        result["current_surface"] = current
    if route:
        result["route_context"] = route
    if trail:
        result["session_trail"] = trail
    return result
