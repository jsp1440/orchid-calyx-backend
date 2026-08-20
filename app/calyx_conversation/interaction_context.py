from __future__ import annotations

from typing import Any

MAX_TRAIL = 8
MAX_TEXT = 240
MAX_QUESTION_TEXT = 4000


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


def sanitize_interaction_context(value: Any) -> dict[str, Any]:
    """Return bounded UI/session context for conversational reference resolution.

    The current user question is preserved as continuity metadata so synthesis
    remains question-centered even when a Brain mission is not launched. It is
    explicitly non-evidentiary and cannot be promoted into scientific knowledge.
    """
    source = value if isinstance(value, dict) else {}
    current = _surface(source.get("current_surface"))
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
    if trail:
        result["session_trail"] = trail
    return result
