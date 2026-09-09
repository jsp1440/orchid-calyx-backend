"""Duplicate suppression audit — Approved Task Priority 27.

Inspect material-change fingerprints, issue/PR head dedupe, repeated
dispatch suppression, and unchanged-run prevention.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "duplicate-suppression-audit/v1"
AUDIT_DATE = "2026-09-09"


class DupeSuppressionStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class DupeSuppressionCriterion:
    criterion_id: str
    area: str
    title: str
    status: str
    authoritative_module: str
    evidence: str
    gap_description: str | None
    blocker_reason: str | None
    next_action: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "area": self.area,
            "title": self.title,
            "status": self.status,
            "authoritative_module": self.authoritative_module,
            "evidence": self.evidence,
            "gap_description": self.gap_description,
            "blocker_reason": self.blocker_reason,
            "next_action": self.next_action,
        }


DUPE_SUPPRESSION_CRITERIA: tuple[DupeSuppressionCriterion, ...] = (

    # ------------------------------------------------------------------ FINGERPRINT
    DupeSuppressionCriterion(
        criterion_id="fingerprint_material_change",
        area="fingerprint",
        title="Material-change fingerprint — WorkIntent.material_fingerprint() SHA-256 of scope fields",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.WorkIntent",
        evidence=(
            "WorkIntent.material_fingerprint(): SHA-256 of canonical scope fields "
            "(scope, risk_tier, target_branch, provider_required, changes_scientific_authority); "
            "identical work produces identical fingerprint — deduplication key for suppression"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DupeSuppressionCriterion(
        criterion_id="fingerprint_factory_decision",
        area="fingerprint",
        title="FactoryDecision carries fingerprint — every gate decision propagates the fingerprint",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.FactoryDecision",
        evidence=(
            "FactoryDecision(frozen=True): action, reason, fingerprint; "
            "fingerprint propagated to every branch of evaluate_factory_gate(); "
            "downstream consumers can compare fingerprints to detect re-submission of same intent"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DupeSuppressionCriterion(
        criterion_id="fingerprint_mission_state_validation",
        area="fingerprint",
        title="MissionState fingerprint non-empty — raises ValueError for blank fingerprint",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.MissionState",
        evidence=(
            "MissionState.__post_init__(): raises ValueError if not self.fingerprint.strip(); "
            "prevents zero-fingerprint missions from entering the suppression comparison; "
            "fingerprint is a required non-empty field for any MissionState"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PR_HEAD_DEDUPE
    DupeSuppressionCriterion(
        criterion_id="pr_head_dedupe_enqueue",
        area="pr_head_dedupe",
        title="PR head deduplication on enqueue — repeated enqueue allowed only to correct stale params",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_engineering.completion_scheduler.EngineeringCompletionScheduler",
        evidence=(
            "enqueue(): 'A repeated enqueue is allowed to correct stale parameters only while the ...'; "
            "same PR number / head SHA combination does not create duplicate active jobs; "
            "correction logic updates stale fields without creating a duplicate record"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DupeSuppressionCriterion(
        criterion_id="pr_head_dedupe_completion_receipt",
        area="pr_head_dedupe",
        title="CompletionReceipt head SHA — receipt carries head_sha for duplicate detection",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_engineering.completion_loop.CompletionReceipt",
        evidence=(
            "CompletionReceipt: head_sha field — identifies the exact PR head processed; "
            "checker must validate against exact head SHA, not just PR number; "
            "head SHA prevents duplicate processing of stale PR states"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DISPATCH_SUPPRESSION
    DupeSuppressionCriterion(
        criterion_id="dispatch_suppression_park_provider",
        area="dispatch_suppression",
        title="Dispatch suppression for NO-API — PARK_PROVIDER_REQUIRED prevents repeated dispatch",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy",
        evidence=(
            "evaluate_factory_gate(): PARK_PROVIDER_REQUIRED returned immediately for provider intents; "
            "parked intents are not re-dispatched while NO-API mode active; "
            "repeated submission of same provider-required intent always returns PARK, not a new dispatch"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DupeSuppressionCriterion(
        criterion_id="dispatch_suppression_checker_verdict",
        area="dispatch_suppression",
        title="Checker verdict deduplication — independent checker verdict needed before AUTO_INTEGRATE",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.CheckerVerdict",
        evidence=(
            "CheckerVerdict: PASS | FAIL | INCONCLUSIVE; "
            "evaluate_factory_gate(): REQUIRE_CHECKER if checker not PASS; "
            "AUTO_INTEGRATE only on PASS — prevents repeated auto-integration attempts"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ UNCHANGED_RUN_PREVENTION
    DupeSuppressionCriterion(
        criterion_id="unchanged_run_mission_state_fingerprint",
        area="unchanged_run_prevention",
        title="Unchanged-run prevention — same fingerprint + same head_sha indicates no-op",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.MissionState",
        evidence=(
            "MissionState: fingerprint + head_sha together identify a unique work unit; "
            "identical fingerprint on unchanged branch means no material change; "
            "factory gate REQUIRE_CHECKER guards against repeated identical runs"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DupeSuppressionCriterion(
        criterion_id="unchanged_run_immutable_artifact_idempotency",
        area="unchanged_run_prevention",
        title="Immutable artifact idempotency — same SHA-256 content hash re-registration is a no-op",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.brain_capture.ImmutableArtifactRegistry",
        evidence=(
            "ImmutableArtifactRegistry: idempotent registration — re-registering same SHA-256 is a no-op; "
            "persisted_patch_verification: before/after digest pair prevents re-applying the same patch; "
            "artifact layer prevents duplicate work at the content-addressable level"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    DupeSuppressionCriterion(
        criterion_id="security_no_credential_in_fingerprint",
        area="security",
        title="No credential in fingerprint — material_fingerprint() hashes only scope-level fields",
        status=DupeSuppressionStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.WorkIntent",
        evidence=(
            "material_fingerprint(): hashes scope, risk_tier, target_branch, provider_required, "
            "changes_scientific_authority — no credential values; "
            "fingerprint is safe to log and compare without credential exposure"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    DupeSuppressionCriterion(
        criterion_id="security_suppression_owner_gated",
        area="security",
        title="Suppression cannot bypass owner gate — OWNER_GATE always overrides dedup logic",
        status=DupeSuppressionStatus.OWNER_GATED,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): OWNER_GATE check is first — before fingerprint comparison; "
            "duplicate suppression cannot shortcut past owner authorization; "
            "a previously-suppressed owner-gated task still requires authorization on re-submission"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any owner-gated task escapes suppression",
    ),
)


@dataclass
class DuplicateSuppressionAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[DupeSuppressionCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[DupeSuppressionCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[DupeSuppressionCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(DupeSuppressionStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(DupeSuppressionStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(DupeSuppressionStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(DupeSuppressionStatus.OWNER_GATED))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audit_date": self.audit_date,
            "no_auto_publication": self.no_auto_publication,
            "no_production_mutation": self.no_production_mutation,
            "summary": {
                "total": len(self.criteria),
                "ready": self.ready_count(),
                "gap": self.gap_count(),
                "blocked": self.blocked_count(),
                "owner_gated": self.owner_gated_count(),
            },
            "criteria": [c.to_dict() for c in self.criteria],
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)


def get_duplicate_suppression_audit() -> DuplicateSuppressionAudit:
    return DuplicateSuppressionAudit(criteria=list(DUPE_SUPPRESSION_CRITERIA))


def get_criteria_by_status(status: str) -> list[DupeSuppressionCriterion]:
    return [c for c in DUPE_SUPPRESSION_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[DupeSuppressionCriterion]:
    return [c for c in DUPE_SUPPRESSION_CRITERIA if c.area == area]


def get_gaps() -> list[DupeSuppressionCriterion]:
    return get_criteria_by_status(DupeSuppressionStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in DUPE_SUPPRESSION_CRITERIA
        if c.next_action
    ]
