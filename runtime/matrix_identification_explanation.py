"""Structured Calyx explanations for governed Matrix Identification sessions.

Narrative generation is strictly downstream of immutable Matrix evidence. Provider
text is presentation, not scoring input, and cannot mutate candidate order, scores,
coverage, observations, or the deterministic next-observation recommendation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from app.calyx_conversation.provider import (
    CalyxReplyProvider,
    DeterministicGovernedReplyProvider,
    configured_reply_provider,
)
from runtime.matrix_identification_session import evaluate_session, get_session

Audience = Literal["beginner", "intermediate", "expert"]
Focus = Literal["summary", "next_observation", "candidate_comparison"]

EXPLANATION_SCHEMA_VERSION = "matrix-identification-explanation/v1"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _candidate_snapshot(report: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for candidate in (report.get("candidates") or [])[:limit]:
        explanations = candidate.get("explanations") or []
        snapshot.append(
            {
                "taxon_id": candidate.get("taxon_id"),
                "scientific_name": candidate.get("scientific_name"),
                "score": candidate.get("score"),
                "coverage": candidate.get("coverage"),
                "supporting_characters": [
                    item.get("character")
                    for item in explanations
                    if item.get("status") == "matched"
                ],
                "partial_characters": [
                    item.get("character")
                    for item in explanations
                    if item.get("status") == "partial"
                ],
                "conflicting_characters": [
                    item.get("character")
                    for item in explanations
                    if item.get("status") == "conflict"
                ],
                "missing_characters": [
                    item.get("character")
                    for item in explanations
                    if item.get("status") == "candidate_state_missing"
                ],
                "provenance": candidate.get("provenance"),
            }
        )
    return snapshot


def build_explanation_evidence(
    evaluation: dict[str, Any],
    *,
    audience: Audience,
    focus: Focus,
) -> dict[str, Any]:
    session = evaluation["session"]
    report = evaluation["report"]
    next_observation = evaluation.get("next_observation")
    evidence = {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "session_id": session["session_id"],
        "session_revision": session.get("revision", 0),
        "registry": report.get("registry") or session.get("registry"),
        "audience": audience,
        "focus": focus,
        "observations": [
            {
                "character": item.get("character"),
                "value": item.get("value"),
                "certainty": item.get("certainty"),
                "review_state": item.get("review_state"),
                "source": item.get("source"),
            }
            for item in session.get("observations", [])
        ],
        "candidate_order": [
            item.get("taxon_id") for item in report.get("candidates", [])
        ],
        "candidates": _candidate_snapshot(report),
        "next_observation": next_observation,
        "disclaimer": report.get("disclaimer"),
        "authority": {
            "matrix_scores_are_authoritative_for_this_packet": True,
            "calyx_may_change_candidate_order": False,
            "calyx_may_change_scores_or_coverage": False,
            "calyx_may_change_next_observation": False,
            "calyx_text_is_scientific_evidence": False,
            "automatic_identification_publication": False,
            "canonical_taxonomy_mutation": False,
        },
    }
    evidence["evidence_digest_sha256"] = _digest(evidence)
    return evidence


def _deterministic_narrative(evidence: dict[str, Any]) -> str:
    candidates = evidence.get("candidates") or []
    next_observation = evidence.get("next_observation")
    lines: list[str] = []
    if candidates:
        first = candidates[0]
        lines.append(
            f"The current leading candidate is {first.get('scientific_name')} based on the supplied Matrix evidence. "
            f"Its match score is {first.get('score')} with coverage {first.get('coverage')}."
        )
        conflicts = first.get("conflicting_characters") or []
        missing = first.get("missing_characters") or []
        if conflicts:
            lines.append("Conflicting characters: " + ", ".join(str(item) for item in conflicts) + ".")
        if missing:
            lines.append(
                "Missing candidate states reduce coverage and are not treated as biological absence: "
                + ", ".join(str(item) for item in missing)
                + "."
            )
        if len(candidates) > 1:
            second = candidates[1]
            lines.append(
                f"The strongest alternative is {second.get('scientific_name')} with score {second.get('score')} "
                f"and coverage {second.get('coverage')}."
            )
    else:
        lines.append("No governed candidates are currently available for explanation.")

    if next_observation:
        label = next_observation.get("label") or next_observation.get("character")
        lines.append(
            f"The Matrix recommends observing {label} next because it has the strongest deterministic "
            "discrimination signal among the remaining unobserved characters."
        )
        if next_observation.get("description"):
            lines.append(str(next_observation["description"]))
    else:
        lines.append("The Matrix does not currently recommend another discriminating observation.")

    lines.append(
        "This is an explanation of candidate-ranking evidence, not a verified taxonomic identification."
    )
    return "\n\n".join(lines)


def _provider_prompt(evidence: dict[str, Any]) -> str:
    audience = evidence["audience"]
    focus = evidence["focus"]
    return (
        "Explain this Orchid Continuum Matrix Identification evidence package. "
        f"Audience: {audience}. Focus: {focus}. "
        "Explain why the leading candidate currently ranks first, why the strongest alternative differs, "
        "and why the deterministic next observation is useful when one is present. "
        "Use plain language first, then botanical terminology where useful. "
        "Do not change candidate order, scores, coverage, observations, or the selected next observation. "
        "Do not call scores probabilities. Do not assert a verified identification. "
        "Treat missing data as unknown, never as biological absence."
    )


def explain_session(
    session_id: str,
    *,
    audience: Audience = "intermediate",
    focus: Focus = "summary",
    provider: CalyxReplyProvider | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    # Confirm the session exists before evaluating so missing-session errors remain precise.
    get_session(session_id, root=root)
    evaluation = evaluate_session(
        session_id,
        root=root,
        registry_root=registry_root,
    )
    evidence = build_explanation_evidence(evaluation, audience=audience, focus=focus)
    deterministic_text = _deterministic_narrative(evidence)

    resolved_provider = provider or configured_reply_provider()
    provider_error: str | None = None
    if isinstance(resolved_provider, DeterministicGovernedReplyProvider):
        text = deterministic_text
        provider_name = "matrix-deterministic-governed"
        model = "calyx-matrix-explanation-v1"
        provider_response_id = None
        request_hash = _digest({"evidence": evidence, "text": text})
    else:
        try:
            reply = resolved_provider.generate(
                messages=[{"role": "user", "content": _provider_prompt(evidence)}],
                governed_context={
                    "matrix_identification": evidence,
                    "epistemic_policy": evidence["authority"],
                    "mission": None,
                    "retrieval": {"status": "not_requested", "results": []},
                    "casual": False,
                },
            )
            text = reply.text
            provider_name = reply.provider
            model = reply.model
            provider_response_id = reply.provider_response_id
            request_hash = reply.request_hash
        except Exception as exc:  # noqa: BLE001
            provider_error = str(exc)
            text = deterministic_text
            provider_name = "matrix-deterministic-governed"
            model = "calyx-matrix-explanation-v1"
            provider_response_id = None
            request_hash = _digest({"evidence": evidence, "text": text})

    # The narrative is returned beside—not inside—the evidence object. Nothing in
    # provider output is parsed back into ranking/session state.
    return {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "session_id": session_id,
        "evidence": evidence,
        "narrative": {
            "text": text,
            "provider": provider_name,
            "model": model,
            "provider_response_id": provider_response_id,
            "request_hash": request_hash,
            "fallback_error": provider_error,
            "epistemic_state": "explanation_not_evidence",
        },
        "invariants": {
            "candidate_order_digest": _digest(evidence["candidate_order"]),
            "next_observation_digest": _digest(evidence.get("next_observation")),
            "provider_output_mutates_matrix_state": False,
        },
    }
