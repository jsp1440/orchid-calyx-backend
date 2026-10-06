"""Audience presentations built from one claim without changing its science.

A presentation is derived data. Every tier carries the same claim statement,
evidence state, mechanism ids and uncertainty statement, and the fingerprint of
that scientific core is identical across tiers. Only structure, scaffolding and
the depth of supporting detail differ.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contract import UNCERTAIN_STATES, ContractViolation, checksum

AUDIENCES: tuple[str, ...] = ("beginner", "inquiry", "advanced")


def scientific_core(claim: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a claim no audience may change."""
    return {
        "claim_id": claim["id"],
        "statement": claim["statement"],
        "evidence_state": claim["evidence_state"],
        "mechanism_ids": sorted(m["id"] for m in claim.get("mechanisms") or []),
        "uncertainty": (claim.get("uncertainty") or {}).get("statement"),
    }


def core_fingerprint(claim: Mapping[str, Any]) -> str:
    return checksum(scientific_core(claim))


def _labels(claim: Mapping[str, Any]) -> list[str]:
    return [m["label"] for m in claim.get("mechanisms") or []]


def build_presentations(claim: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    mechanisms = list(claim.get("mechanisms") or [])
    uncertain = claim["evidence_state"] in UNCERTAIN_STATES
    uncertainty = (claim.get("uncertainty") or {}).get("statement")
    if uncertain and not uncertainty:
        raise ContractViolation("UNCERTAIN_CLAIM_WITHOUT_UNCERTAINTY_STATEMENT")
    fingerprint = core_fingerprint(claim)
    labels = _labels(claim)
    common = {
        "claim_id": claim["id"],
        "statement": claim["statement"],
        "evidence_state": claim["evidence_state"],
        "mechanism_ids": [m["id"] for m in mechanisms],
        "uncertainty": uncertainty,
        "core_fingerprint": fingerprint,
    }

    beginner = {
        **common,
        "audience": "beginner",
        "structure": "compare_hypotheses_side_by_side",
        "headline": (
            f"Scientists have {len(mechanisms)} explanations for this and have not settled "
            "which is right."
            if uncertain and len(mechanisms) > 1
            else f"What we know: {claim['statement']}"
        ),
        "body": [f"Explanation {i}: {label}" for i, label in enumerate(labels, 1)],
        "scaffold": "Use one plain-language sentence per explanation and keep them visually parallel.",
        "disclosure": "summary_first",
        "detail": "none",
    }

    inquiry_tasks = []
    for mechanism in mechanisms:
        observation = mechanism.get("distinguishing_observation")
        inquiry_tasks.append(
            {
                "mechanism_id": mechanism["id"],
                "task": (
                    f"What would you expect to observe if '{mechanism['label']}' were true? "
                    + (f"Check against: {observation}" if observation else
                       "No distinguishing observation is recorded; treat this as an open question.")
                ),
                "open_question": not observation,
            }
        )
    inquiry = {
        **common,
        "audience": "inquiry",
        "structure": "predict_observe_compare",
        "headline": "Investigate: which explanation do the observations favour?",
        "body": inquiry_tasks,
        "scaffold": "Students predict, observe, compare, then state what the evidence cannot yet decide.",
        "disclosure": "task_first",
        "detail": "evidence_on_request",
        "assessment": "Students must state the uncertainty, not pick a winner the evidence does not support.",
    }

    advanced = {
        **common,
        "audience": "advanced",
        "structure": "evidence_matrix",
        "headline": claim["statement"],
        "body": [
            {
                "mechanism_id": m["id"],
                "label": m["label"],
                "evidence_refs": list(m.get("evidence_refs") or []),
            }
            for m in mechanisms
        ],
        "uncertainty_reason": (claim.get("uncertainty") or {}).get("reason"),
        "provenance": [dict(p) for p in claim.get("provenance") or []],
        "scaffold": "None; full evidence, provenance and the reason the dispute is unresolved.",
        "disclosure": "full",
        "detail": "full_provenance",
    }
    return {"beginner": beginner, "inquiry": inquiry, "advanced": advanced}


def verify_presentation(claim: Mapping[str, Any], presentation: Mapping[str, Any]) -> None:
    """Raise unless ``presentation`` keeps every material qualification of ``claim``."""
    core = scientific_core(claim)
    if presentation.get("claim_id") != core["claim_id"]:
        raise ContractViolation("PRESENTATION_CLAIM_MISMATCH")
    if presentation.get("evidence_state") != core["evidence_state"]:
        raise ContractViolation("QUALIFICATION_REMOVED:evidence_state")
    shown = set(presentation.get("mechanism_ids") or ())
    missing = set(core["mechanism_ids"]) - shown
    if missing:
        raise ContractViolation(f"QUALIFICATION_REMOVED:mechanism:{','.join(sorted(missing))}")
    if core["uncertainty"] and presentation.get("uncertainty") != core["uncertainty"]:
        raise ContractViolation("QUALIFICATION_REMOVED:uncertainty")
    if presentation.get("core_fingerprint") != core_fingerprint(claim):
        raise ContractViolation("PRESENTATION_CORE_CHANGED")
