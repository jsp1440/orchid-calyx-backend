"""Adapter from Calyx findings to governed Improvement-Discovery candidates.

Reuses ``app.cognitive_integration.improvement_discovery.ImprovementCandidate``
so every Calyx proposal inherits its invariants: human review required, and no
authority to modify governance, promote a hypothesis or activate a conclusion.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.cognitive_integration.improvement_discovery import (
    Deficiency,
    ImprovementCandidate,
)

from .contract import PROHIBITED_ACTIONS, ContractViolation, checksum, validate_advisory

#: Finding kind -> module-lane key (see ``app.autonomy.module_lanes``).
ROUTES: dict[str, str] = {
    "educational_gap": "university-education",
    "curriculum_gap": "university-education",
    "teaching_opportunity": "university-education",
    "ux_gap": "frontend-ux",
    "accessibility_gap": "frontend-ux",
}

MAX_CANDIDATES = 5

SAFETY_GATES: tuple[str, ...] = (
    "brain-authoritative-for-science",
    "scientific-effect-none",
    "no-protected-locality",
    "no-main-merge",
    "no-production-deploy",
    "no-spend-increase",
    "human-review-required",
)


def to_candidates(
    advisory: Mapping[str, Any],
    artifact: Mapping[str, Any],
    *,
    max_candidates: int = MAX_CANDIDATES,
    known_fingerprints: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Bounded, deduplicated candidates; ``no_action`` yields none."""
    validate_advisory(advisory)
    if advisory["artifact_id"] != artifact.get("artifact_id") or advisory[
        "artifact_checksum"
    ] != checksum(artifact):
        raise ContractViolation("ADVISORY_ARTIFACT_MISMATCH")
    out: list[dict[str, Any]] = []
    for finding in advisory["findings"]:
        if finding["kind"] == "no_action":
            continue
        fingerprint = checksum(["calyx", advisory["artifact_id"], finding["kind"], finding["targets"]])[:16]
        if fingerprint in known_fingerprints or any(c["fingerprint"] == fingerprint for c in out):
            continue
        candidate = ImprovementCandidate(
            deficiency=Deficiency.MISSING_CAPABILITY,
            statement=finding["rationale"],
            why_it_matters=(
                f"{finding['kind']} ({finding['severity']}) on {', '.join(finding['targets'])}: "
                "learners may misread or be unable to use the science as stated."
            ),
            bounded_next_step=finding["recommendation"],
            blocks_question="none — the reasoning is complete without it",
            evidence=list(finding["evidence"]),
        )
        out.append({
            **candidate.to_record(),
            "fingerprint": fingerprint,
            "source": "calyx-advisory",
            "finding_id": finding["finding_id"],
            "finding_kind": finding["kind"],
            "target_module": ROUTES[finding["kind"]],
            "acceptance_criteria": [
                "scientific core fingerprint of every affected claim is unchanged",
                "every competing mechanism and the uncertainty statement remain visible",
                "change is evaluated against the finding's evidence, not asserted",
            ],
            "provenance": {
                "advisory_contract": advisory["contract"],
                "artifact_id": advisory["artifact_id"],
                "artifact_checksum": advisory["artifact_checksum"],
            },
            "safety_gates": list(SAFETY_GATES),
            "prohibited_actions": list(PROHIBITED_ACTIONS),
        })
        if len(out) >= max_candidates:
            break
    return out
