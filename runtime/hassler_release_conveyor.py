"""Deterministic next-step planner for the governed Hassler taxonomy intake.

This module turns the read-only lifecycle evidence from
``runtime.hassler_release_lifecycle`` into one explicit next action.  It does not
perform uploads, staging, activation, relinking, Knowledge Graph publication, or
any other mutation.

The purpose is operational: a new Hassler release should move through one
repeatable conveyor instead of requiring a new ad-hoc plan every time the source
is updated.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CONTRACT_VERSION = "calyx-hassler-release-conveyor/v1"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _step(
    *,
    code: str,
    action: str,
    reason: str,
    mode: str,
    owner_approval_required: bool,
    scientific_review_required: bool = False,
) -> dict[str, Any]:
    """Build one non-authoritative conveyor step."""
    return {
        "code": code,
        "action": action,
        "reason": reason,
        "mode": mode,
        "owner_approval_required": owner_approval_required,
        "scientific_review_required": scientific_review_required,
        # Permanent non-authority assertions.  A planner is not an executor.
        "execution_authorized": False,
        "production_mutation_authorized": False,
        "taxonomy_activation_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "scientific_publication_authorized": False,
    }


def build_release_conveyor_plan(
    *,
    lifecycle: Mapping[str, Any],
    downstream: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return exactly one next action for the currently observed release state.

    The planner is deliberately conservative:

    * unavailable evidence never becomes absence;
    * staging never becomes activation;
    * an open review queue always outranks activation readiness;
    * downstream relinking is never authorized by this plan.
    """
    state = str(lifecycle.get("lifecycle_state") or "UNAVAILABLE")
    staging = _mapping(lifecycle.get("staging"))
    downstream_map = _mapping(downstream)

    if state == "UNAVAILABLE":
        next_step = _step(
            code="REFRESH_READ_ONLY_EVIDENCE",
            action="rerun the read-only release lifecycle discovery",
            reason="the exact release state cannot be determined from the available probes",
            mode="read_only",
            owner_approval_required=False,
        )
    elif state == "ABSENT":
        next_step = _step(
            code="UPLOAD_EXACT_RELEASE",
            action="upload and inspect the checksum-verified exact Hassler release",
            reason="the durable release list was read successfully and the exact release is absent",
            mode="production_intake_write",
            owner_approval_required=True,
        )
    elif state == "UPLOADED_INSPECTED":
        next_step = _step(
            code="RUN_SMOKE_READBACK",
            action="run the bounded smoke/readback gate for the inspected release",
            reason="the release is durable and inspected but smoke verification is not yet established",
            mode="read_only_validation",
            owner_approval_required=False,
        )
    elif state == "SMOKE_VERIFIED":
        next_step = _step(
            code="START_BOUNDED_STAGING",
            action="stage the next bounded batch from row zero",
            reason="smoke/readback passed and no staging progress is recorded",
            mode="production_staging_write",
            owner_approval_required=True,
        )
    elif state == "STAGING_IN_PROGRESS":
        next_index = staging.get("next_row_index")
        suffix = (
            f" from row {next_index}"
            if next_index is not None
            else " from the durable checkpoint"
        )
        next_step = _step(
            code="RESUME_BOUNDED_STAGING",
            action=f"resume the next bounded staging batch{suffix}",
            reason="staging is incomplete and the existing checkpoint must be resumed rather than restarted",
            mode="production_staging_write",
            owner_approval_required=True,
        )
    elif state == "STAGED_COMPLETE":
        open_review = staging.get("open_review_items")
        change_report_present = staging.get("change_report_present")
        if isinstance(open_review, int) and open_review > 0:
            next_step = _step(
                code="RESOLVE_TAXONOMY_REVIEW_QUEUE",
                action="review and disposition the open taxonomy change items with durable provenance",
                reason=f"{open_review} taxonomy review item(s) remain open after staging",
                mode="scientific_review",
                owner_approval_required=True,
                scientific_review_required=True,
            )
        elif change_report_present is not True:
            next_step = _step(
                code="VERIFY_CHANGE_REPORT",
                action="produce or verify the staged release change report before any activation decision",
                reason="staging is complete but a durable change report is not established",
                mode="read_only_validation",
                owner_approval_required=False,
            )
        else:
            next_step = _step(
                code="PREPARE_OWNER_ACTIVATION_DECISION",
                action="build the read-only activation-decision packet for owner review",
                reason="staging is complete, the change report exists, and no open review items are reported",
                mode="read_only_governance",
                owner_approval_required=True,
            )
    elif state == "ACTIVATED":
        unresolved = list(downstream_map.get("unresolved_blockers") or [])
        counts_complete = downstream_map.get("counts_complete")
        if unresolved or counts_complete is not True:
            next_step = _step(
                code="AUDIT_DOWNSTREAM_RELINK_IMPACT",
                action="complete the read-only downstream relink/backfill impact audit",
                reason="the release is active but downstream impact evidence is incomplete or blocked",
                mode="read_only_validation",
                owner_approval_required=False,
            )
        else:
            next_step = _step(
                code="PREPARE_DOWNSTREAM_RELINK",
                action="prepare the separately reviewed downstream relink/backfill execution plan",
                reason="the release is active and downstream impact evidence is complete",
                mode="planning_only",
                owner_approval_required=True,
            )
    elif state == "SUPERSEDED":
        next_step = _step(
            code="SWITCH_TO_NEWER_RELEASE",
            action="select the newest verified durable release as the intake target and recompute its lifecycle",
            reason="a newer durable release exists, so continuing the older release would create immediate taxonomy debt",
            mode="read_only_target_selection",
            owner_approval_required=False,
        )
    else:
        next_step = _step(
            code="REFRESH_READ_ONLY_EVIDENCE",
            action="rerun the read-only release lifecycle discovery",
            reason=f"unrecognized lifecycle state {state!r} cannot be advanced safely",
            mode="read_only",
            owner_approval_required=False,
        )

    return {
        "contract": CONTRACT_VERSION,
        "read_only": True,
        "lifecycle_state": state,
        "next_step": next_step,
        "repeatable_conveyor": [
            "discover",
            "upload_inspect",
            "smoke_readback",
            "bounded_stage",
            "scientific_review",
            "owner_activation_decision",
            "activate_separately",
            "downstream_relink_audit",
            "downstream_relink_separately",
        ],
        "automatic_promotion": False,
        "execution_authorized": False,
        "production_taxonomy_mutation_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "scientific_publication_authorized": False,
    }
