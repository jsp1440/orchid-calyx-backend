"""Brain <-> Calyx disagreement contract.

Brain is authoritative. When Calyx objects that a scientifically correct
statement is hard to teach, the only acceptable responses change *presentation*.
A request that would remove a material qualification (a competing mechanism, the
uncertainty, the contested state) is not applied and not silently dropped: it
becomes a bounded design mission to teach the qualification better.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contract import ContractViolation, checksum

SCHEMA = "calyx_brain_disagreement.v1"

#: Changes that alter presentation only.
PRESENTATION_CHANGES = frozenset(
    {"simplify_language", "add_scaffold", "progressive_disclosure", "add_visual", "add_worked_example"}
)
#: Changes that would remove a qualification. Never applied.
QUALIFICATION_REMOVING = frozenset(
    {"remove_mechanism", "drop_uncertainty", "pick_single_answer", "hide_contradiction", "merge_mechanisms"}
)


def resolve(brain: Mapping[str, Any], calyx: Mapping[str, Any]) -> dict[str, Any]:
    """Return the decision record for one Brain/Calyx disagreement.

    ``brain``: ``claim_id``, ``position``, ``evidence_state``, ``mechanism_ids``,
    ``uncertainty``. ``calyx``: ``claim_id``, ``concern``, ``audience``,
    ``requested_change``. Unknown requests fail closed to Brain review rather
    than being treated as harmless.
    """
    for key in ("claim_id", "position", "evidence_state"):
        if not brain.get(key):
            raise ContractViolation(f"BRAIN_POSITION_REQUIRES_{key.upper()}")
    for key in ("claim_id", "concern", "requested_change"):
        if not calyx.get(key):
            raise ContractViolation(f"CALYX_POSITION_REQUIRES_{key.upper()}")
    if brain["claim_id"] != calyx["claim_id"]:
        raise ContractViolation("DISAGREEMENT_CLAIM_MISMATCH")

    change = str(calyx["requested_change"])
    mission = None
    if change in PRESENTATION_CHANGES:
        decision = "accepted_presentation_change"
    elif change in QUALIFICATION_REMOVING:
        decision = "rejected_qualification_removal"
        mission = _design_mission(brain, calyx)
    else:
        decision = "needs_brain_review"

    record = {
        "schema": SCHEMA,
        "claim_id": brain["claim_id"],
        "authority": "brain",
        "brain_position": dict(brain),
        "calyx_concern": {k: calyx.get(k) for k in ("concern", "audience", "requested_change")},
        "decision": decision,
        "scientific_conclusion_unchanged": True,
        "design_mission": mission,
    }
    record["checksum"] = checksum({k: v for k, v in record.items() if k != "checksum"})
    return record


def _design_mission(brain: Mapping[str, Any], calyx: Mapping[str, Any]) -> dict[str, Any]:
    audience = calyx.get("audience") or "beginner"
    return {
        "schema": "calyx_design_mission.v1",
        "claim_id": brain["claim_id"],
        "audience": audience,
        "problem": calyx["concern"],
        "must_preserve": {
            "evidence_state": brain["evidence_state"],
            "mechanism_ids": list(brain.get("mechanism_ids") or []),
            "uncertainty": brain.get("uncertainty"),
        },
        "must_not": ["remove_mechanism", "drop_uncertainty", "pick_single_answer"],
        "acceptance_criteria": [
            "every mechanism id remains visible to the audience",
            "the uncertainty statement is shown unchanged",
            f"the {audience} presentation is evaluated with comprehension evidence, not asserted",
            "the scientific core fingerprint is identical before and after",
        ],
        "bounded": True,
    }
