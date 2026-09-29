"""Governance admission gate for RunEvidenceManifest-gated scientific actions.

This module is the executable link between the immutable run evidence manifest
(Brain #103 vertical slice) and the governance/admission step in the autonomous
research loop.

Given a RunEvidenceManifest and a proposed action, it returns a deterministic
admission decision driven entirely by the manifest's governance flags. No model
inference, no provider calls, no network, no database. The function can be called
from a FastAPI route, a workflow gate, or a direct test.

Governance rules (all hardcoded in every manifest built by build_run_evidence_manifest):
  - canonical_knowledge_mutation_allowed: always False
  - automatic_scientific_publication_allowed: always False
  - canonical_activation_requires_human_authority: always True
  - human_review_required: always True

Actions:
  canonical_knowledge_mutation   — blocked; requires canonical_knowledge_mutation_allowed
  automatic_scientific_publication — blocked; requires automatic_scientific_publication_allowed
  canonical_activation           — blocked; requires canonical_activation_requires_human_authority=False
  human_review_submission        — always admitted (this is how humans record decisions)
  read_evidence                  — always admitted
  build_synthesis                — admitted unless verification_state is evidence_incomplete
  build_manifest                 — always admitted
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

MANIFEST_CONTRACT = "oc-run-evidence-manifest-v1"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")

_ALWAYS_ADMITTED = frozenset(
    {"human_review_submission", "read_evidence", "build_manifest"}
)

_KNOWN_ACTIONS = frozenset(
    {
        "canonical_knowledge_mutation",
        "automatic_scientific_publication",
        "canonical_activation",
        "human_review_submission",
        "read_evidence",
        "build_synthesis",
        "build_manifest",
    }
)


class GovernanceOutcome(StrEnum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    outcome: GovernanceOutcome
    admitted: bool
    reason: str
    blocking_flags: list[str] = field(default_factory=list)


def check_manifest_governance(
    manifest: dict[str, Any],
    proposed_action: str,
) -> GovernanceDecision:
    """Return an admission decision for *proposed_action* given *manifest*.

    Parameters
    ----------
    manifest:
        A dict matching the oc-run-evidence-manifest-v1 contract as returned
        by build_run_evidence_manifest. Must carry a 64-char hex run_fingerprint.
    proposed_action:
        One of the known governance actions (see module docstring).

    Returns
    -------
    GovernanceDecision
        admitted=True when the action is unconditionally permitted by the
        manifest's governance flags; admitted=False otherwise, with blocking_flags
        listing the exact manifest fields that block it.

    Raises
    ------
    ValueError
        UNKNOWN_ACTION — action is not in the governed action set.
        MANIFEST_CONTRACT_INVALID — contract_version is not oc-run-evidence-manifest-v1.
        MANIFEST_FINGERPRINT_MISSING — run_fingerprint is absent or malformed.
    """
    if proposed_action not in _KNOWN_ACTIONS:
        raise ValueError(f"UNKNOWN_ACTION:{proposed_action}")

    contract = manifest.get("contract_version", "")
    if contract != MANIFEST_CONTRACT:
        raise ValueError(f"MANIFEST_CONTRACT_INVALID:{contract!r}")

    fingerprint = str(manifest.get("run_fingerprint", ""))
    if not _FINGERPRINT_RE.match(fingerprint):
        raise ValueError("MANIFEST_FINGERPRINT_MISSING")

    if proposed_action in _ALWAYS_ADMITTED:
        return GovernanceDecision(
            outcome=GovernanceOutcome.ADMITTED,
            admitted=True,
            reason="UNCONDITIONALLY_PERMITTED",
        )

    if proposed_action == "build_synthesis":
        v_state = manifest.get("verification_state", "")
        if v_state == "evidence_incomplete":
            return GovernanceDecision(
                outcome=GovernanceOutcome.BLOCKED,
                admitted=False,
                reason="EVIDENCE_INCOMPLETE_BLOCKS_SYNTHESIS",
                blocking_flags=["verification_state:evidence_incomplete"],
            )
        return GovernanceDecision(
            outcome=GovernanceOutcome.ADMITTED,
            admitted=True,
            reason="VERIFICATION_STATE_PERMITS_SYNTHESIS",
        )

    if proposed_action == "canonical_knowledge_mutation":
        if not manifest.get("canonical_knowledge_mutation_allowed", False):
            return GovernanceDecision(
                outcome=GovernanceOutcome.BLOCKED,
                admitted=False,
                reason="CANONICAL_MUTATION_NOT_AUTHORIZED",
                blocking_flags=["canonical_knowledge_mutation_allowed:false"],
            )
        return GovernanceDecision(
            outcome=GovernanceOutcome.ADMITTED,
            admitted=True,
            reason="CANONICAL_MUTATION_AUTHORIZED",
        )

    if proposed_action == "automatic_scientific_publication":
        if not manifest.get("automatic_scientific_publication_allowed", False):
            return GovernanceDecision(
                outcome=GovernanceOutcome.BLOCKED,
                admitted=False,
                reason="AUTOMATIC_PUBLICATION_NOT_AUTHORIZED",
                blocking_flags=["automatic_scientific_publication_allowed:false"],
            )
        return GovernanceDecision(
            outcome=GovernanceOutcome.ADMITTED,
            admitted=True,
            reason="AUTOMATIC_PUBLICATION_AUTHORIZED",
        )

    if proposed_action == "canonical_activation":
        if manifest.get("canonical_activation_requires_human_authority", True):
            return GovernanceDecision(
                outcome=GovernanceOutcome.BLOCKED,
                admitted=False,
                reason="CANONICAL_ACTIVATION_REQUIRES_HUMAN_AUTHORITY",
                blocking_flags=["canonical_activation_requires_human_authority:true"],
            )
        return GovernanceDecision(
            outcome=GovernanceOutcome.ADMITTED,
            admitted=True,
            reason="CANONICAL_ACTIVATION_AUTHORIZED",
        )

    # Should not be reachable — _KNOWN_ACTIONS covers all cases above.
    raise ValueError(f"UNKNOWN_ACTION:{proposed_action}")  # pragma: no cover
