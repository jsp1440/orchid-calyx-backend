"""Review-gated bridge from contributor images into Matrix Identification sessions.

Machine-extracted character values remain review-required suggestions until a
reviewer explicitly accepts or revises them; only then do they enter Matrix
scoring as governed observations with full contributor, image, and machine
provenance. Rejected or unmapped extractions are retained as audit provenance
and never scored. Nothing here promotes an AI-inferred character to verified
scientific evidence: every emitted record is labeled
``unverified_candidate_evidence``.

Follows the same governance contract as runtime/matrix_identification_vision.py
(Vision review gate), reusing the governed session store and registry binding.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from runtime.matrix_identification import state_similarity
from runtime.matrix_identification_registry import get_registry_version
from runtime.matrix_identification_session import (
    _write,
    add_observation,
    evaluate_session,
    get_session,
)

EVIDENCE_SCHEMA_VERSION = "matrix-contributor-evidence/v1"

ContributorDecision = Literal["accept", "revise", "reject"]
SuggestionState = Literal[
    "pending_review",
    "needs_mapping",
    "accepted",
    "revised",
    "rejected",
]

_CERTAINTIES = {"certain", "probable", "uncertain", "unknown"}

UNVERIFIED_STATUS = "unverified_candidate_evidence"
PROMOTION_RULE = (
    "This record is candidate-ranking evidence derived from a reviewed "
    "contributor image. Promotion to verified scientific evidence requires "
    "independent expert verification and is a separate governed action; "
    "machine-extracted values are never promoted automatically."
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _image_dict(staged_image: Any) -> dict[str, Any]:
    if hasattr(staged_image, "as_dict"):
        return staged_image.as_dict()
    if isinstance(staged_image, dict):
        return dict(staged_image)
    raise TypeError("staged_image must be a StagedContributorImage or mapping")


def _bound_registry(session: dict[str, Any], *, registry_root=None) -> dict[str, Any]:
    registry_ref = session["registry"]
    registry = get_registry_version(
        registry_ref["registry_id"], registry_ref["version"], root=registry_root
    )
    if registry.get("checksum_sha256") != registry_ref.get("checksum_sha256"):
        raise ValueError("registry checksum drift detected for identification session")
    return registry


def _registry_character_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["character"]): item
        for item in registry.get("characters", [])
        if item.get("character")
    }


def _suggestion_id(session_id: str, content_sha256: str, character: str, value: Any) -> str:
    canonical_value = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orchid-continuum:matrix-contributor:{session_id}:{content_sha256}:{character}:{canonical_value}",
        )
    )


def attach_contributor_extractions(
    session_id: str,
    staged_image: Any,
    extractions: list[dict[str, Any]],
    *,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    """Attach machine-extracted characters as review-required suggestions.

    Extractions are proposed values only. They do not score until an explicit
    review decision accepts or revises them.
    """
    image = _image_dict(staged_image)
    if not image.get("content_sha256") or not image.get("submission_id"):
        raise ValueError("staged contributor image identity is required")
    session = get_session(session_id, root=root, access_actor=access_actor)
    registry = _bound_registry(session, registry_root=registry_root)
    character_map = _registry_character_map(registry)

    images = session.setdefault("contributor_images", {})
    images[str(image["submission_id"])] = image

    existing = {
        item.get("suggestion_id"): item
        for item in session.get("contributor_suggestions", [])
        if item.get("suggestion_id")
    }
    added = 0
    for extraction in extractions:
        character = str(extraction.get("character") or "").strip()
        if not character:
            raise ValueError("extraction character is required")
        value = extraction.get("value")
        suggestion_id = _suggestion_id(
            session_id, str(image["content_sha256"]), character, value
        )
        if suggestion_id in existing:
            continue
        character_meta = character_map.get(character)
        state: SuggestionState = "pending_review" if character_meta else "needs_mapping"
        existing[suggestion_id] = {
            "suggestion_id": suggestion_id,
            "session_id": session_id,
            "submission_id": str(image["submission_id"]),
            "content_sha256": str(image["content_sha256"]),
            "character": character,
            "registry_character_found": character_meta is not None,
            "proposed_value": value,
            "machine_confidence": extraction.get("machine_confidence"),
            "extractor": extraction.get("extractor"),
            "extractor_version": extraction.get("extractor_version"),
            "extraction_method": extraction.get("extraction_method"),
            "limitations": list(extraction.get("limitations") or []),
            "state": state,
            "created_at": _now(),
            "review": None,
            "matrix_observation_id": None,
        }
        added += 1

    session["contributor_suggestions"] = list(existing.values())
    session["updated_at"] = _now()
    _write(session, root=root)
    return {
        "session_id": session_id,
        "submission_id": str(image["submission_id"]),
        "added": added,
        "suggestions": session["contributor_suggestions"],
        "rule": "Contributor extractions require explicit review before Matrix scoring.",
    }


def list_contributor_suggestions(
    session_id: str,
    *,
    access_actor: str | None = None,
    state: str | None = None,
    root=None,
) -> dict[str, Any]:
    """Read contributor images and review-gated suggestions for one session.

    Read-only. Owner scoping is enforced by the governed session store exactly
    as in session reads: cross-owner access fails closed as session-not-found.
    """
    session = get_session(session_id, root=root, access_actor=access_actor)
    suggestions = list(session.get("contributor_suggestions", []))
    if state is not None:
        suggestions = [item for item in suggestions if item.get("state") == state]
    return {
        "session_id": session_id,
        "revision": session.get("revision"),
        "contributor_images": session.get("contributor_images", {}),
        "suggestions": suggestions,
        "suggestion_count": len(suggestions),
        "rule": "Suggestions never score until explicitly accepted or revised.",
    }


def review_contributor_suggestion(
    session_id: str,
    suggestion_id: str,
    *,
    decision: ContributorDecision,
    reviewer: str,
    certainty: str | None = None,
    revised_value: Any = None,
    comments: str | None = None,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    """Review one suggestion; only accepted/revised output enters Matrix evidence."""
    session = get_session(session_id, root=root, access_actor=access_actor)
    suggestion = next(
        (
            item
            for item in session.get("contributor_suggestions", [])
            if item.get("suggestion_id") == suggestion_id
        ),
        None,
    )
    if suggestion is None:
        raise FileNotFoundError(f"contributor suggestion not found: {suggestion_id}")
    if suggestion.get("state") in {"accepted", "revised", "rejected"}:
        raise ValueError("contributor suggestion already has a final Matrix review decision")
    if not reviewer.strip():
        raise ValueError("reviewer identity is required")

    review = {
        "decision": decision,
        "reviewer": reviewer,
        "certainty": certainty,
        "comments": comments,
        "reviewed_at": _now(),
        "machine_value_preserved": suggestion.get("proposed_value"),
    }

    if decision == "reject":
        suggestion["state"] = "rejected"
        suggestion["review"] = review
        session["updated_at"] = _now()
        _write(session, root=root)
        return {"session": session, "suggestion": suggestion, "observation_added": False}

    if certainty not in _CERTAINTIES:
        raise ValueError("certainty is required for accepted or revised suggestions")

    if decision == "accept":
        if suggestion.get("state") != "pending_review":
            raise ValueError(
                "suggestion cannot be accepted without an unambiguous Matrix mapping"
            )
        value = suggestion.get("proposed_value")
        final_state: SuggestionState = "accepted"
    elif decision == "revise":
        if revised_value is None:
            raise ValueError("revised_value is required when revising a contributor suggestion")
        value = revised_value
        final_state = "revised"
    else:
        raise ValueError(f"unsupported contributor review decision: {decision}")

    image = (session.get("contributor_images") or {}).get(
        str(suggestion.get("submission_id")), {}
    )
    updated = add_observation(
        session_id,
        character=suggestion["character"],
        value=value,
        certainty=certainty,
        source={
            "kind": "contributor_image_reviewed",
            "decision": decision,
            "reviewer": reviewer,
            "submission_id": suggestion.get("submission_id"),
            "content_sha256": suggestion.get("content_sha256"),
            "original_object_ref": image.get("original_object_ref"),
            "contributor_id": image.get("contributor_id"),
            "contributor_display_name": image.get("contributor_display_name"),
            "permission_grant": image.get("permission_grant"),
            "attribution_line": image.get("attribution_line"),
            "machine_confidence": suggestion.get("machine_confidence"),
            "extractor": suggestion.get("extractor"),
            "extractor_version": suggestion.get("extractor_version"),
            "extraction_method": suggestion.get("extraction_method"),
            "limitations": suggestion.get("limitations", []),
            "comments": comments,
        },
        actor=reviewer,
        access_actor=access_actor,
        root=root,
        registry_root=registry_root,
    )
    matrix_observation = updated["observations"][-1]

    session = get_session(session_id, root=root, access_actor=access_actor)
    suggestion = next(
        item
        for item in session.get("contributor_suggestions", [])
        if item.get("suggestion_id") == suggestion_id
    )
    suggestion["state"] = final_state
    suggestion["review"] = review
    suggestion["matrix_observation_id"] = matrix_observation["observation_id"]
    suggestion["accepted_value"] = value
    session["updated_at"] = _now()
    _write(session, root=root)
    return {"session": session, "suggestion": suggestion, "observation_added": True}


def compare_with_governed_sources(
    session: dict[str, Any],
    report: dict[str, Any],
    source_assertions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare scored observations against registry states and existing source evidence.

    ``source_assertions`` are existing governed source records (e.g. loaded via
    runtime/matrix_relationship_sources.load_governed_assertions or the knowledge
    graph). Absence of a source record is reported as ``no_source_evidence`` and
    is never treated as biological absence.
    """
    assertions_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for assertion in source_assertions or []:
        key = (
            str(assertion.get("subject_id") or ""),
            str(assertion.get("character") or ""),
        )
        assertions_by_key.setdefault(key, []).append(assertion)

    rows: list[dict[str, Any]] = []
    observations = session.get("observations", [])
    for candidate in report.get("candidates", []):
        explanations = {
            item.get("character"): item for item in candidate.get("explanations", [])
        }
        for observation in observations:
            character = observation.get("character")
            explanation = explanations.get(character, {})
            observed_value = observation.get("value")
            matched = assertions_by_key.get((str(candidate.get("taxon_id")), str(character)), [])
            source_refs = [
                {
                    "source_ref": item.get("source_ref"),
                    "citation": item.get("citation"),
                    "value": item.get("value"),
                }
                for item in matched
            ]
            if not matched:
                agreement = "no_source_evidence"
            elif any(
                state_similarity(observed_value, item.get("value")) == 1.0
                for item in matched
            ):
                agreement = "supports"
            else:
                agreement = "conflicts"
            rows.append(
                {
                    "observation_id": observation.get("observation_id"),
                    "character": character,
                    "observed_value": observed_value,
                    "certainty": observation.get("certainty"),
                    "taxon_id": candidate.get("taxon_id"),
                    "scientific_name": candidate.get("scientific_name"),
                    "candidate_state": explanation.get("candidate_state"),
                    "matrix_similarity": explanation.get("similarity"),
                    "source_agreement": agreement,
                    "source_refs": source_refs,
                }
            )
    return rows


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def build_contributor_evidence_record(
    session_id: str,
    staged_image: Any,
    *,
    source_assertions: list[dict[str, Any]] | None = None,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    """Freeze the current contributor-evidence state into a content-addressed record.

    The checksum covers the complete scientific payload (image identity, session
    revision, registry identity, reviewed observations, machine audit trail,
    candidate ranking, source comparison). ``created_at`` is metadata outside
    the checksum, so identical evidence state yields an identical checksum.
    """
    image = _image_dict(staged_image)
    session = get_session(session_id, root=root, access_actor=access_actor)
    registry = _bound_registry(session, registry_root=registry_root)
    evaluation = evaluate_session(
        session_id, access_actor=access_actor, root=root, registry_root=registry_root
    )
    report = evaluation["report"]

    payload: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "contributor_image": {
            "submission_id": image.get("submission_id"),
            "batch_id": image.get("batch_id"),
            "content_sha256": image.get("content_sha256"),
            "original_object_ref": image.get("original_object_ref"),
            "mime_type": image.get("mime_type"),
            "contributor_id": image.get("contributor_id"),
            "contributor_display_name": image.get("contributor_display_name"),
            "attribution_line": image.get("attribution_line"),
            "permission_grant": image.get("permission_grant"),
            "taxon_name": image.get("taxon_name"),
            "taxon_certainty": image.get("taxon_certainty"),
            "candidate_taxa": list(image.get("candidate_taxa") or []),
            "canonical_taxon_id": image.get("canonical_taxon_id"),
            "reconciliation_state": image.get("reconciliation_state"),
            "provenance": image.get("provenance") or {},
        },
        "session": {
            "session_id": session.get("session_id"),
            "revision": session.get("revision", 0),
            "actor": session.get("actor"),
        },
        "registry": {
            "registry_id": registry.get("registry_id"),
            "version": registry.get("version"),
            "checksum_sha256": registry.get("checksum_sha256"),
            "publication_state": registry.get("publication_state"),
        },
        "reviewed_observations": [
            {
                "observation_id": item.get("observation_id"),
                "character": item.get("character"),
                "value": item.get("value"),
                "certainty": item.get("certainty"),
                "source": item.get("source"),
                "recorded_by": item.get("recorded_by"),
            }
            for item in session.get("observations", [])
        ],
        "machine_suggestions_audit": [
            {
                "suggestion_id": item.get("suggestion_id"),
                "character": item.get("character"),
                "proposed_value": item.get("proposed_value"),
                "machine_confidence": item.get("machine_confidence"),
                "extractor": item.get("extractor"),
                "extractor_version": item.get("extractor_version"),
                "state": item.get("state"),
                "review": item.get("review"),
                "matrix_observation_id": item.get("matrix_observation_id"),
            }
            for item in session.get("contributor_suggestions", [])
        ],
        "candidate_ranking": {
            "candidates": [
                {
                    "taxon_id": item.get("taxon_id"),
                    "scientific_name": item.get("scientific_name"),
                    "score": item.get("score"),
                    "coverage": item.get("coverage"),
                }
                for item in report.get("candidates", [])
            ],
            "disclaimer": report.get("disclaimer"),
        },
        "source_comparison": compare_with_governed_sources(
            session, report, source_assertions or []
        ),
        "verification_status": UNVERIFIED_STATUS,
        "promotion_rule": PROMOTION_RULE,
    }
    record = dict(payload)
    record["checksum_sha256"] = hashlib.sha256(_canonical_payload(payload)).hexdigest()
    record["created_at"] = _now()
    record["note"] = (
        "Governed Matrix evidence record. Candidate ranking is hypothesis-generating "
        "evidence, not a taxonomic determination; unreviewed machine suggestions "
        "appear only in the audit section and are never scored."
    )
    return record
