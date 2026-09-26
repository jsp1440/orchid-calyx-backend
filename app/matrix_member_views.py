"""Member-shaped Matrix identification responses (explicit schemas, no pass-through).

A member receives the identification output -- ranked candidate taxa, per-character
ranking explanations, the registry identity/checksum the ranking is bound to, and the
deterministic next observation -- and nothing else. Every member payload is BUILT
from an explicit key list; nothing is copied through wholesale. In particular a
member never receives:

* any account identifier (session ``actor``, observation ``recorded_by``, registry
  ``created_by``) -- sessions carry ``mine: true`` instead;
* character-level registry provenance or free-form registry/candidate provenance
  keys beyond a short citation allow-list (no specimen, locality, reviewer or
  submitter fields can pass, whatever the registry author put there);
* registry ``scope`` keys other than taxonomic ranks;
* session ``metadata`` or observation ``source`` fields beyond ``kind``/``interface``.

Owner and API-key callers keep receiving the unmodified runtime payloads.
"""

from __future__ import annotations

from typing import Any

# Registry scope: taxonomic ranks only, scalar string values.
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
CHARACTER_KEYS = (
    "character",
    "label",
    "description",
    "value_type",
    "weight",
    "concept_id",
)
NEXT_OBSERVATION_KEYS = (
    "character",
    "label",
    "description",
    "value_type",
    "concept_id",
    "matrix_weight",
    "candidate_coverage",
    "distinct_state_count",
    "candidate_count",
    "selection_score",
    "reason_code",
    "explanation_boundary",
)
EXPLANATION_KEYS = (
    "character",
    "observation",
    "candidate_state",
    "certainty",
    "effective_weight",
    "similarity",
    "contribution",
    "status",
)
OBSERVATION_KEYS = (
    "observation_id",
    "revision",
    "character",
    "value",
    "certainty",
    "weight",
    "review_state",
    "created_at",
)
MAX_TEXT = 300
MEMBER_SOURCE_KIND = "user_observation"


def _scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT]
    return None


def _pick_scalars(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    picked: dict[str, Any] = {}
    for key in keys:
        if key in value:
            scalar = _scalar(value[key])
            if scalar is not None:
                picked[key] = scalar
    return picked


def _pick(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def member_scope(scope: Any) -> dict[str, Any]:
    return {
        key: val
        for key, val in _pick_scalars(scope, SCOPE_KEYS).items()
        if isinstance(val, str)
    }


def member_provenance(provenance: Any) -> dict[str, Any] | None:
    if provenance is None:
        return None
    return _pick_scalars(provenance, PROVENANCE_KEYS)


def member_registry_ref(registry: Any) -> dict[str, Any]:
    registry = registry if isinstance(registry, dict) else {}
    ref = _pick(
        registry, ("registry_id", "version", "checksum_sha256", "publication_state")
    )
    if "scope" in registry:
        ref["scope"] = member_scope(registry.get("scope"))
    return ref


def member_registry_summary(summary: dict[str, Any]) -> dict[str, Any]:
    item = _pick(
        summary,
        (
            "registry_id",
            "version",
            "title",
            "candidate_count",
            "character_count",
            "created_at",
            "checksum_sha256",
            "publication_state",
        ),
    )
    item["scope"] = member_scope(summary.get("scope"))
    return item


def member_registry_listing(versions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "versions": [member_registry_summary(item) for item in versions],
        "read_only_listing": True,
    }


def member_registry_detail(record: dict[str, Any]) -> dict[str, Any]:
    """Character definitions for the guided flow; candidate states and provenance withheld."""
    characters = [
        _pick(item, CHARACTER_KEYS)
        for item in record.get("characters", [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": record.get("schema_version"),
        "registry_id": record.get("registry_id"),
        "version": record.get("version"),
        "title": record.get("title"),
        "scope": member_scope(record.get("scope")),
        "checksum_sha256": record.get("checksum_sha256"),
        "publication_state": record.get("publication_state"),
        "character_count": len(characters),
        "candidate_count": len(record.get("candidates", []) or []),
        "characters": characters,
        "member_view": True,
    }


def member_next_observation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _pick(value, NEXT_OBSERVATION_KEYS)


def member_observation(item: dict[str, Any]) -> dict[str, Any]:
    observation = _pick(item, OBSERVATION_KEYS)
    source = _pick_scalars(item.get("source"), ("kind", "interface"))
    observation["source"] = {
        key: val for key, val in source.items() if isinstance(val, str)
    }
    return observation


def member_session(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": record.get("session_id"),
        "schema_version": record.get("schema_version"),
        "registry": member_registry_ref(record.get("registry")),
        "observations": [
            member_observation(item)
            for item in record.get("observations", [])
            if isinstance(item, dict)
        ],
        "revision": record.get("revision", 0),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "next_observation": member_next_observation(record.get("next_observation")),
        "mine": True,
    }


def member_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    item = _pick(
        candidate,
        (
            "taxon_id",
            "scientific_name",
            "score",
            "coverage",
            "compared_weight",
            "possible_weight",
        ),
    )
    item["explanations"] = [
        _pick(explanation, EXPLANATION_KEYS)
        for explanation in candidate.get("explanations", []) or []
        if isinstance(explanation, dict)
    ]
    item["provenance"] = member_provenance(candidate.get("provenance"))
    return item


def member_report(report: dict[str, Any]) -> dict[str, Any]:
    shaped = _pick(
        report,
        (
            "observation_count",
            "compared_character_count",
            "disclaimer",
            "session_id",
            "revision",
        ),
    )
    shaped["candidates"] = [
        member_candidate(item)
        for item in report.get("candidates", []) or []
        if isinstance(item, dict)
    ]
    if "registry" in report:
        shaped["registry"] = member_registry_ref(report.get("registry"))
    return shaped


def member_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "session": member_session(evaluation.get("session") or {}),
        "report": member_report(evaluation.get("report") or {}),
        "next_observation": member_next_observation(evaluation.get("next_observation")),
    }


def member_session_metadata(metadata: Any) -> dict[str, Any]:
    """Persist only the guided-flow markers a member client sends."""
    picked = _pick_scalars(metadata, ("input_mode", "client"))
    return {key: val[:64] for key, val in picked.items() if isinstance(val, str)}


def member_observation_source(source: Any) -> dict[str, Any]:
    """Members record their own observations; the source kind is not caller-chosen."""
    interface = _pick_scalars(source, ("interface",)).get("interface")
    shaped: dict[str, Any] = {"kind": MEMBER_SOURCE_KIND}
    if isinstance(interface, str) and interface:
        shaped["interface"] = interface[:64]
    return shaped
