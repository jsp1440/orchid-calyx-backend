"""Governed Matrix identification workflow (Phase 3).

Builds a complete, explainable identification report for one governed Matrix
session, connecting:

* reviewed contributor observations (the only scored evidence),
* the existing deterministic candidate-ranking engine,
* per-candidate supporting / partial / contradicting / missing characters,
* taxonomic resolution with explicit synonym reconciliation,
* contributor-image provenance links for every scored character,
* explicit uncertainty, ambiguity, and identification limitations,
* the review-gate state (unreviewed machine suggestions are excluded from
  scoring and reported separately as audit provenance).

The report is a hypothesis-generating candidate ranking, not a taxonomic
determination. Missing candidate states reduce coverage and are never treated
as biological absence. The checksum covers the full scientific payload;
``created_at`` is metadata outside the checksum so identical evidence state
yields an identical checksum (idempotent, restart-stable reporting).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from runtime.matrix_contributor_bridge import (
    _bound_registry,
    compare_with_governed_sources,
)
from runtime.matrix_identification_session import evaluate_session, get_session
from runtime.matrix_taxon_resolution import (
    TaxonResolver,
    collapse_synonym_candidates,
    resolver_from_candidates,
)

IDENTIFICATION_REPORT_SCHEMA = "matrix-identification-report/v1"

DEFAULT_AMBIGUITY_EPSILON = 0.05

_BASE_LIMITATIONS = [
    "Candidate ranking is hypothesis-generating evidence, not a taxonomic determination.",
    "Missing candidate states reduce coverage and are never treated as biological absence.",
    "Only reviewer-accepted observations are scored; unreviewed machine suggestions are excluded from scoring and appear only as audit provenance.",
    "Reviewer certainty is recorded independently and is never copied from machine confidence.",
]

_AUTOMATION_STAGES = [
    {
        "stage": "contributor_image_intake",
        "actor": "automated",
        "detail": "Batch staging, checksum, dedup, and session opening are automated; permission and attribution validation fail closed.",
    },
    {
        "stage": "character_extraction",
        "actor": "automated_only_when_authorized_extractor_configured",
        "detail": (
            "Machine extraction attaches review-required suggestions. Without an "
            "authorized extractor, characters come from explicit contributor-supplied "
            "or expert manual entry through the same review gate. Image-based "
            "identification is never claimed from contributor-supplied labels."
        ),
    },
    {
        "stage": "expert_review",
        "actor": "human",
        "detail": "Accept / revise / reject decisions and reviewer certainty are always human actions.",
    },
    {
        "stage": "candidate_scoring",
        "actor": "automated",
        "detail": "Deterministic ranking over reviewed observations only (existing Matrix engine).",
    },
    {
        "stage": "identification_report",
        "actor": "automated",
        "detail": "Evidence explanation, taxon resolution, uncertainty, and provenance assembly are deterministic.",
    },
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _observation_provenance(observation: dict[str, Any]) -> dict[str, Any]:
    source = observation.get("source") or {}
    return {
        "observation_id": observation.get("observation_id"),
        "recorded_by": observation.get("recorded_by"),
        "source_kind": source.get("kind"),
        "reviewer": source.get("reviewer"),
        "review_decision": source.get("decision"),
        "submission_id": source.get("submission_id"),
        "content_sha256": source.get("content_sha256"),
        "original_object_ref": source.get("original_object_ref"),
        "contributor_display_name": source.get("contributor_display_name"),
        "attribution_line": source.get("attribution_line"),
        "permission_grant": source.get("permission_grant"),
    }


def _character_rows(
    candidate: dict[str, Any],
    observations_by_character: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {
        "supporting_characters": [],
        "partial_characters": [],
        "contradicting_characters": [],
        "missing_candidate_states": [],
        "unknown_observations": [],
    }
    for explanation in candidate.get("explanations", []):
        status = explanation.get("status")
        character = explanation.get("character")
        provenance = [
            _observation_provenance(item)
            for item in observations_by_character.get(character, [])
        ]
        row = {
            "character": character,
            "observed_value": explanation.get("observation"),
            "candidate_state": explanation.get("candidate_state"),
            "certainty": explanation.get("certainty"),
            "similarity": explanation.get("similarity"),
            "contribution": explanation.get("contribution"),
            "evidence_links": provenance,
        }
        if status == "matched":
            rows["supporting_characters"].append(row)
        elif status == "partial":
            rows["partial_characters"].append(row)
        elif status == "conflict":
            rows["contradicting_characters"].append(row)
        elif status == "candidate_state_missing":
            row["note"] = (
                "Candidate has no recorded state for this character; coverage is "
                "reduced but this is not evidence of biological absence."
            )
            rows["missing_candidate_states"].append(row)
        elif status == "ignored_unknown_observation":
            row["note"] = "Unknown observations score zero for every candidate."
            rows["unknown_observations"].append(row)
    return rows


def build_identification_report(
    session_id: str,
    *,
    limit: int = 20,
    ambiguity_epsilon: float = DEFAULT_AMBIGUITY_EPSILON,
    taxon_resolver: TaxonResolver | None = None,
    synonym_entries: list[dict[str, Any]] | None = None,
    source_assertions: list[dict[str, Any]] | None = None,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    """Build the governed identification report for one session.

    Read-only with respect to evidence: the only write is the session's own
    ``latest_evaluation`` cache performed by the existing ``evaluate_session``.
    """
    if ambiguity_epsilon < 0:
        raise ValueError("ambiguity_epsilon must be >= 0")
    session = get_session(session_id, root=root, access_actor=access_actor)
    registry = _bound_registry(session, registry_root=registry_root)
    evaluation = evaluate_session(
        session_id, limit=limit, access_actor=access_actor, root=root,
        registry_root=registry_root,
    )
    report = evaluation["report"]
    registry_candidates = list(registry.get("candidates", []))

    resolver: TaxonResolver = taxon_resolver or resolver_from_candidates(
        registry_candidates, extra_entries=synonym_entries
    )

    observations = list(session.get("observations", []))
    observations_by_character: dict[str, list[dict[str, Any]]] = {}
    for item in observations:
        observations_by_character.setdefault(str(item.get("character")), []).append(item)

    ranked: list[dict[str, Any]] = []
    for candidate in report.get("candidates", []):
        resolution = resolver.resolve(str(candidate.get("scientific_name") or ""))
        rows = _character_rows(candidate, observations_by_character)
        ranked.append(
            {
                "taxon_id": candidate.get("taxon_id"),
                "scientific_name": candidate.get("scientific_name"),
                "score": candidate.get("score"),
                "coverage": candidate.get("coverage"),
                "taxonomic_resolution": resolution.as_dict(),
                **rows,
                "candidate_provenance": candidate.get("provenance"),
            }
        )

    synonym_groups = collapse_synonym_candidates(report.get("candidates", []), resolver)
    collapsed_groups = [group for group in synonym_groups if group["collapsed"]]

    observed_characters = {str(item.get("character")) for item in observations}
    unobserved_characters = [
        {
            "character": item.get("character"),
            "label": item.get("label"),
            "weight": item.get("weight"),
            "note": "Registry character with no reviewed observation; potential next evidence.",
        }
        for item in registry.get("characters", [])
        if item.get("character") and str(item.get("character")) not in observed_characters
    ]

    suggestions = list(session.get("contributor_suggestions", []))
    review_gate: dict[str, Any] = {
        "suggestion_counts": {},
        "excluded_from_scoring": [],
    }
    for item in suggestions:
        state = str(item.get("state"))
        review_gate["suggestion_counts"][state] = (
            review_gate["suggestion_counts"].get(state, 0) + 1
        )
        if state in {"pending_review", "needs_mapping", "rejected"}:
            review_gate["excluded_from_scoring"].append(
                {
                    "suggestion_id": item.get("suggestion_id"),
                    "character": item.get("character"),
                    "state": state,
                    "reason": (
                        "unreviewed machine suggestion"
                        if state in {"pending_review", "needs_mapping"}
                        else "reviewer rejected"
                    ),
                }
            )
    review_gate["rule"] = (
        "Only accepted/revised suggestions became scored observations; every "
        "excluded suggestion is preserved as audit provenance."
    )

    # Ambiguity: leaders whose scores are indistinguishable within epsilon.
    ambiguity: dict[str, Any] = {
        "epsilon": ambiguity_epsilon,
        "is_ambiguous": False,
        "leader_group": [],
    }
    if ranked:
        top = ranked[0]
        leaders = [
            item
            for item in ranked
            if abs(float(item["score"]) - float(top["score"])) <= ambiguity_epsilon
        ]
        ambiguity["is_ambiguous"] = len(leaders) > 1
        ambiguity["leader_group"] = [
            {
                "taxon_id": item["taxon_id"],
                "scientific_name": item["scientific_name"],
                "accepted_name": item["taxonomic_resolution"]["accepted_name"],
                "score": item["score"],
            }
            for item in leaders
        ]

    limitations = list(_BASE_LIMITATIONS)
    if not observations:
        limitations.append(
            "No reviewed observations exist yet; all candidates score zero and the "
            "ranking carries no evidential weight."
        )
    unresolved = [
        item["scientific_name"]
        for item in ranked
        if item["taxonomic_resolution"]["resolution_state"] == "unresolved"
    ]
    if unresolved:
        limitations.append(
            "Some candidate names could not be reconciled against the resolver "
            f"entry set: {sorted(unresolved)}. They are reported under their "
            "supplied names without canonical reconciliation."
        )
    if collapsed_groups:
        limitations.append(
            "Synonym reconciliation merged some ranked rows into shared accepted "
            "taxa; both names remain visible in synonym_groups."
        )
    if ambiguity["is_ambiguous"]:
        limitations.append(
            "Leading candidates are indistinguishable within the configured score "
            "epsilon; additional discriminating characters are required before any "
            "determination could be considered."
        )
    if unobserved_characters:
        limitations.append(
            f"{len(unobserved_characters)} registry character(s) have no reviewed "
            "observation; the ranking is based on partial evidence."
        )

    payload: dict[str, Any] = {
        "schema_version": IDENTIFICATION_REPORT_SCHEMA,
        "session": {
            "session_id": session.get("session_id"),
            "revision": session.get("revision", 0),
            "actor": session.get("actor"),
        },
        "registry": {
            "registry_id": registry.get("registry_id"),
            "version": registry.get("version"),
            "checksum_sha256": registry.get("checksum_sha256"),
        },
        "ranked_candidates": ranked,
        "synonym_groups": synonym_groups,
        "unobserved_characters": unobserved_characters,
        "ambiguity": ambiguity,
        "review_gate": review_gate,
        "contributor_images": {
            key: {
                "submission_id": value.get("submission_id"),
                "content_sha256": value.get("content_sha256"),
                "original_object_ref": value.get("original_object_ref"),
                "attribution_line": value.get("attribution_line"),
                "permission_grant": value.get("permission_grant"),
                "contributor_display_name": value.get("contributor_display_name"),
                "taxon_name": value.get("taxon_name"),
                "taxon_certainty": value.get("taxon_certainty"),
            }
            for key, value in (session.get("contributor_images") or {}).items()
        },
        "source_comparison": compare_with_governed_sources(
            session, report, source_assertions or []
        ),
        "observation_count": report.get("observation_count"),
        "compared_character_count": report.get("compared_character_count"),
        "automation_stages": _AUTOMATION_STAGES,
        "limitations": limitations,
        "disclaimer": report.get("disclaimer"),
        "next_observation_recommendation": evaluation.get("next_observation"),
    }
    record = dict(payload)
    record["checksum_sha256"] = hashlib.sha256(_canonical_payload(payload)).hexdigest()
    record["created_at"] = _now()
    return record
