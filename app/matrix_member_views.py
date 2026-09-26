"""Member-shaped Matrix identification responses (explicit schemas, fail closed).

A member receives the identification output -- ranked candidate taxa, per-character
ranking explanations, the registry identity/checksum the ranking is bound to, and the
deterministic next observation -- and nothing else.

Every member payload is BUILT field by field: each field has an explicit shaper
(identifier, label, prose, number, enum, timestamp, matrix state). Nothing is copied
through wholesale, and no nested ``Any`` value is ever passed through:

* Matrix states (``candidate_state``, observation ``value``) must be a bool, a finite
  number, a short screened string token, a bounded list of those, or a numeric
  ``{"min", "max"}`` range. A range is rebuilt from ``min``/``max`` alone, so extra
  keys planted inside it (specimen, locality, coordinates) are dropped; any other
  shape becomes the explicit marker ``"withheld"``.
* Every string is length-bounded and screened for locality/specimen/submitter
  material (coordinate-shaped numbers, degree marks, locality/specimen/collector
  vocabulary, e-mail marks). A string that fails the screen becomes ``"withheld"``.
* No account identifier is returned (session ``actor``, observation ``recorded_by``,
  registry ``created_by``) -- sessions carry ``mine: true`` instead.
* Registry ``scope`` keeps taxonomic-rank keys only; candidate provenance keeps a
  short citation allow-list; character provenance, session ``metadata`` and
  observation ``source`` fields beyond ``kind``/``interface`` are never returned.

Owner and API-key callers keep receiving the unmodified runtime payloads.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable
from typing import Any

WITHHELD = "withheld"
MEMBER_SOURCE_KIND = "user_observation"

MAX_IDENTIFIER = 200
MAX_LABEL = 300
MAX_PROSE = 2000
MAX_STATE_TEXT = 120
MAX_STATE_ITEMS = 50

# Registry scope: taxonomic ranks only, screened string values.
SCOPE_KEYS = (
    "kingdom",
    "family",
    "subfamily",
    "tribe",
    "subtribe",
    "clade",
    "genus",
    "section",
    "species",
    "rank",
    "taxon",
)
# Candidate provenance: citation-style keys only, scalar values.
PROVENANCE_KEYS = (
    "source",
    "citation",
    "reference",
    "publication",
    "doi",
    "dataset",
    "license",
    "release",
    "authority",
)
CERTAINTIES = frozenset({"certain", "probable", "uncertain", "unknown"})
EXPLANATION_STATUSES = frozenset(
    {
        "matched",
        "partial",
        "conflict",
        "candidate_state_missing",
        "ignored_unknown_observation",
    }
)
VALUE_TYPES = frozenset({"categorical", "multi_state", "numeric", "numeric_range"})

# --- screens ---------------------------------------------------------------------

_SENSITIVE_WORDS = re.compile(
    r"latitud|longitud|localit|coordinat|georef|\bgps\b|\blat\b|\blon\b|\blng\b"
    r"|specimen|voucher|collector|herbari|elevation|altitude|@",
    re.IGNORECASE,
)
_COORDINATE_SHAPES = re.compile(
    r"\d\.\d{3,}"  # coordinate-precision decimals
    r"|-?\d{1,3}\.\d+\s*[,;]\s*-?\d{1,3}\.\d+"  # decimal pairs
    r"|[°º˚′″]"  # degree / minute / second marks
    r"|\b\d{1,3}\s*deg(?:rees?)?\b",
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(r"[\w.:/+()'&× -]{1,200}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?"
)
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]{1,200}")


def screened_text(value: Any, max_len: int = MAX_LABEL) -> str | None:
    """A bounded string with no locality/specimen/submitter material, else WITHHELD."""
    if value is None:
        return None
    if not isinstance(value, str):
        return WITHHELD
    if (
        len(value) > max_len
        or _SENSITIVE_WORDS.search(value)
        or _COORDINATE_SHAPES.search(value)
    ):
        return WITHHELD
    return value


def _uuid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value))) if isinstance(value, str) else WITHHELD
    except ValueError:
        return WITHHELD


def _identifier(value: Any) -> str | None:
    text = screened_text(value, MAX_IDENTIFIER)
    if text in (None, WITHHELD):
        return text
    return text if _IDENTIFIER.fullmatch(text) else WITHHELD


def _label(value: Any) -> str | None:
    return screened_text(value, MAX_LABEL)


def _prose(value: Any) -> str | None:
    return screened_text(value, MAX_PROSE)


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _enum(allowed: frozenset[str]) -> Callable[[Any], str | None]:
    def shape(value: Any) -> str | None:
        if value is None:
            return None
        return value if isinstance(value, str) and value in allowed else WITHHELD

    return shape


def _hex64(value: Any) -> str | None:
    return value if isinstance(value, str) and _HEX64.fullmatch(value) else None


def _timestamp(value: Any) -> str | None:
    return value if isinstance(value, str) and _TIMESTAMP.fullmatch(value) else None


def _state_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else WITHHELD
    if isinstance(value, str):
        return screened_text(value, MAX_STATE_TEXT)
    return WITHHELD


def member_state(value: Any) -> Any:
    """Shape a Matrix state or observation value against the explicit state schema."""
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_STATE_ITEMS:
            return WITHHELD
        return [_state_scalar(item) for item in value]
    if isinstance(value, dict):
        low, high = _number(value.get("min")), _number(value.get("max"))
        if low is None or high is None:
            return WITHHELD
        return {"min": low, "max": high}
    return _state_scalar(value)


def _shape(record: Any, schema: dict[str, Callable[[Any], Any]]) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    return {key: shaper(record[key]) for key, shaper in schema.items() if key in record}


def _text_map(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: _label(value[key]) for key in keys if isinstance(value.get(key), str)}


# --- registry ----------------------------------------------------------------------


def member_scope(scope: Any) -> dict[str, Any]:
    return _text_map(scope, SCOPE_KEYS)


def member_provenance(provenance: Any) -> dict[str, Any] | None:
    if provenance is None:
        return None
    if not isinstance(provenance, dict):
        return {}
    shaped: dict[str, Any] = {}
    for key in PROVENANCE_KEYS:
        value = provenance.get(key)
        if key == "doi" and isinstance(value, str) and _DOI.fullmatch(value):
            shaped[key] = value
        elif isinstance(value, str):
            shaped[key] = _label(value)
        elif isinstance(value, bool) or _number(value) is not None:
            shaped[key] = value
    return shaped


_REGISTRY_REF: dict[str, Callable[[Any], Any]] = {
    "registry_id": _identifier,
    "version": _identifier,
    "checksum_sha256": _hex64,
    "publication_state": _identifier,
}


def member_registry_ref(registry: Any) -> dict[str, Any]:
    ref = _shape(registry, _REGISTRY_REF)
    if isinstance(registry, dict) and "scope" in registry:
        ref["scope"] = member_scope(registry.get("scope"))
    return ref


_REGISTRY_SUMMARY: dict[str, Callable[[Any], Any]] = {
    **_REGISTRY_REF,
    "title": _label,
    "candidate_count": _number,
    "character_count": _number,
    "created_at": _timestamp,
}


def member_registry_summary(summary: dict[str, Any]) -> dict[str, Any]:
    item = _shape(summary, _REGISTRY_SUMMARY)
    item["scope"] = member_scope(summary.get("scope"))
    return item


def member_registry_listing(versions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "versions": [member_registry_summary(item) for item in versions],
        "read_only_listing": True,
    }


_CHARACTER: dict[str, Callable[[Any], Any]] = {
    "character": _identifier,
    "label": _label,
    "description": _prose,
    "value_type": _enum(VALUE_TYPES),
    "weight": _number,
    "concept_id": _uuid,
}


def member_registry_detail(record: dict[str, Any]) -> dict[str, Any]:
    """Character definitions for the guided flow; candidate states and provenance withheld."""
    characters = [
        _shape(item, _CHARACTER)
        for item in record.get("characters", [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": _identifier(record.get("schema_version")),
        "registry_id": _identifier(record.get("registry_id")),
        "version": _identifier(record.get("version")),
        "title": _label(record.get("title")),
        "scope": member_scope(record.get("scope")),
        "checksum_sha256": _hex64(record.get("checksum_sha256")),
        "publication_state": _identifier(record.get("publication_state")),
        "character_count": len(characters),
        "candidate_count": len(record.get("candidates", []) or []),
        "characters": characters,
        "member_view": True,
    }


# --- sessions and rankings ---------------------------------------------------------

_NEXT_OBSERVATION: dict[str, Callable[[Any], Any]] = {
    "character": _identifier,
    "label": _label,
    "description": _prose,
    "value_type": _enum(VALUE_TYPES),
    "concept_id": _uuid,
    "matrix_weight": _number,
    "candidate_coverage": _number,
    "distinct_state_count": _number,
    "candidate_count": _number,
    "selection_score": _number,
    "reason_code": _identifier,
    "explanation_boundary": _prose,
}


def member_next_observation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _shape(value, _NEXT_OBSERVATION)


_OBSERVATION: dict[str, Callable[[Any], Any]] = {
    "observation_id": _uuid,
    "revision": _number,
    "character": _identifier,
    "value": member_state,
    "certainty": _enum(CERTAINTIES),
    "weight": _number,
    "review_state": _identifier,
    "created_at": _timestamp,
}


def member_observation(item: dict[str, Any]) -> dict[str, Any]:
    observation = _shape(item, _OBSERVATION)
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    observation["source"] = {
        key: _identifier(source[key])
        for key in ("kind", "interface")
        if isinstance(source.get(key), str)
    }
    return observation


def member_session(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": _uuid(record.get("session_id")),
        "schema_version": _identifier(record.get("schema_version")),
        "registry": member_registry_ref(record.get("registry")),
        "observations": [
            member_observation(item)
            for item in record.get("observations", [])
            if isinstance(item, dict)
        ],
        "revision": _number(record.get("revision", 0)),
        "status": _identifier(record.get("status")),
        "created_at": _timestamp(record.get("created_at")),
        "updated_at": _timestamp(record.get("updated_at")),
        "next_observation": member_next_observation(record.get("next_observation")),
        "mine": True,
    }


_EXPLANATION: dict[str, Callable[[Any], Any]] = {
    "character": _identifier,
    "observation": member_state,
    "candidate_state": member_state,
    "certainty": _enum(CERTAINTIES),
    "effective_weight": _number,
    "similarity": _number,
    "contribution": _number,
    "status": _enum(EXPLANATION_STATUSES),
}
_CANDIDATE: dict[str, Callable[[Any], Any]] = {
    "taxon_id": _identifier,
    "scientific_name": _label,
    "score": _number,
    "coverage": _number,
    "compared_weight": _number,
    "possible_weight": _number,
}


def member_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    item = _shape(candidate, _CANDIDATE)
    item["explanations"] = [
        _shape(explanation, _EXPLANATION)
        for explanation in candidate.get("explanations", []) or []
        if isinstance(explanation, dict)
    ]
    item["provenance"] = member_provenance(candidate.get("provenance"))
    return item


_REPORT: dict[str, Callable[[Any], Any]] = {
    "observation_count": _number,
    "compared_character_count": _number,
    "disclaimer": _prose,
    "session_id": _uuid,
    "revision": _number,
}


def member_report(report: dict[str, Any]) -> dict[str, Any]:
    shaped = _shape(report, _REPORT)
    shaped["candidates"] = [
        member_candidate(item)
        for item in report.get("candidates", []) or []
        if isinstance(item, dict)
    ]
    if "registry" in report:
        shaped["registry"] = member_registry_ref(report.get("registry"))
    return shaped


def member_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Member view of an evaluation; also the only input a member explanation sees."""
    return {
        "session": member_session(evaluation.get("session") or {}),
        "report": member_report(evaluation.get("report") or {}),
        "next_observation": member_next_observation(evaluation.get("next_observation")),
    }


# --- member inputs -----------------------------------------------------------------


def member_session_metadata(metadata: Any) -> dict[str, Any]:
    """Persist only the guided-flow markers a member client sends."""
    if not isinstance(metadata, dict):
        return {}
    return {
        key: metadata[key][:64]
        for key in ("input_mode", "client")
        if isinstance(metadata.get(key), str) and metadata[key]
    }


def member_observation_source(source: Any) -> dict[str, Any]:
    """Members record their own observations; the source kind is not caller-chosen."""
    interface = source.get("interface") if isinstance(source, dict) else None
    shaped: dict[str, Any] = {"kind": MEMBER_SOURCE_KIND}
    if isinstance(interface, str) and interface:
        shaped["interface"] = interface[:64]
    return shaped
