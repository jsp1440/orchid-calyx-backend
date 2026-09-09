"""Integration-to-main gates audit — Approved Task Priority 34.

Inspect integration/main drift, owner-gated promotion PRs, production risk,
branch protection, and deployment coupling.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "integration-promotion-audit/v1"
AUDIT_DATE = "2026-09-09"


class IntegrationPromotionAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class IntegrationPromotionCriterion:
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


INTEGRATION_PROMOTION_CRITERIA: tuple[IntegrationPromotionCriterion, ...] = (

    # ------------------------------------------------------------------ MAIN_PROTECTION
    IntegrationPromotionCriterion(
        criterion_id="main_protection_owner_gate",
        area="main_protection",
        title="main/master is owner-gated — factory gate refuses AUTO_INTEGRATE to main or master",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "_requires_owner(intent): target in {'main', 'master'} → True; "
            "evaluate_factory_gate(): _requires_owner True → OWNER_GATE with reason 'OWNER_GOVERNED_BOUNDARY'; "
            "FactoryAction.OWNER_GATE returned — no autonomous promotion to main or master"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="main_protection_exception_policy",
        area="main_protection",
        title="integration_main_promotion is a PROTECTED_BOUNDARY — exception_policy enforces owner gate",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.autonomy.exception_policy.PROTECTED_BOUNDARIES",
        evidence=(
            "PROTECTED_BOUNDARIES['integration_main_promotion'] = 'integration_main_promotion'; "
            "classify_exception(protected_boundary='integration_main_promotion'): "
            "exception_class='owner_exception', owner_decision_required=True; "
            "integration-to-main promotion cannot proceed without explicit owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="main_protection_integration_branch_only",
        area="main_protection",
        title="AUTO_INTEGRATE targets non-main branches only — factory gate is narrower than merge authority",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "factory_policy.py docstring: 'This gate is intentionally narrower than a merge/deploy authority system. "
            "It may authorize integration only into a non-main integration branch after independent checker success'; "
            "CLAUDE.md: 'Safe, reversible low/moderate-risk changes targeting a non-main integration branch "
            "may advance without owner relay when factory_policy.evaluate_factory_gate() returns AUTO_INTEGRATE'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ PRODUCTION_RISK
    IntegrationPromotionCriterion(
        criterion_id="production_risk_touches_production",
        area="production_risk",
        title="touches_production is owner-gated — production-touching work cannot auto-integrate",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy._requires_owner",
        evidence=(
            "_requires_owner(intent): intent.touches_production → True → OWNER_GATE; "
            "WorkIntent.touches_production: bool = False (default); "
            "any change that touches_production is classified as requiring owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="production_risk_destructive",
        area="production_risk",
        title="Destructive operations are owner-gated — non-reversible changes cannot auto-integrate",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy._requires_owner",
        evidence=(
            "_requires_owner(): intent.destructive → True → OWNER_GATE; "
            "_requires_owner(): not intent.reversible → True → OWNER_GATE; "
            "both reversibility and non-destructive intent are required for factory AUTO_INTEGRATE"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="production_risk_high_tier_owner_gated",
        area="production_risk",
        title="HIGH and OWNER_GATED risk tiers require owner — even after checker success",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): intent.risk_tier in {RiskTier.HIGH, RiskTier.OWNER_GATED} → "
            "OWNER_GATE with reason 'RISK_TIER_<tier>_REQUIRES_OWNER'; "
            "this check occurs after checker validation — high risk never auto-integrates"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ VALIDATION_GATES
    IntegrationPromotionCriterion(
        criterion_id="validation_independent_checker",
        area="validation_gates",
        title="Independent checker required — checker_id must differ from maker_id",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.ValidationEvidence",
        evidence=(
            "ValidationEvidence.independent_checker: bool(checker_id) and checker_id != maker_id; "
            "evaluate_factory_gate(): not evidence.independent_checker → REQUIRE_CHECKER 'INDEPENDENT_CHECKER_REQUIRED'; "
            "CLAUDE.md: 'The implementation session is the maker and cannot self-certify an automatic integration'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="validation_exact_head_required",
        area="validation_gates",
        title="Exact-head validation required — checker must verify exact commit SHA",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): not evidence.exact_head_verified → REQUIRE_CHECKER 'EXACT_HEAD_VALIDATION_REQUIRED'; "
            "ValidationEvidence.exact_head_verified: bool = False (default); "
            "exact-head validation is required independently of checker identity"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="validation_required_checks_passed",
        area="validation_gates",
        title="Required checks must be proven — required_checks_passed required for AUTO_INTEGRATE",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): not evidence.required_checks_passed → REQUIRE_CHECKER 'REQUIRED_CHECKS_NOT_PROVEN'; "
            "CLAUDE.md: 'Checker PASS plus exact-head verification is necessary but not sufficient: "
            "the factory risk gate must also return AUTO_INTEGRATE'; "
            "required checks are a separate gate from checker identity and head verification"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="validation_checker_fail_routes_repair",
        area="validation_gates",
        title="Checker FAIL routes to repair — failed checker triggers PREPARE_REPAIR not promotion",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.evaluate_factory_gate",
        evidence=(
            "evaluate_factory_gate(): evidence.checker_verdict is CheckerVerdict.FAIL → PREPARE_REPAIR 'CHECKER_REJECTED_CHANGE'; "
            "CLAUDE.md: 'Checker FAIL routes to bounded repair'; "
            "pending/inconclusive checker verdict → REQUIRE_CHECKER — not auto-integrated"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ CREDENTIAL_SCIENTIFIC_PROTECTION
    IntegrationPromotionCriterion(
        criterion_id="protection_credentials_owner_gated",
        area="credential_scientific_protection",
        title="Credential changes are owner-gated — any credential change cannot auto-integrate",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy._requires_owner",
        evidence=(
            "_requires_owner(): intent.changes_credentials → True → OWNER_GATE; "
            "WorkIntent.changes_credentials: bool = False (default); "
            "CLAUDE.md: 'No credential value may be requested, printed, logged, copied, or committed'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="protection_scientific_authority_owner_gated",
        area="credential_scientific_protection",
        title="Scientific authority changes are owner-gated — taxonomy/KG mutations cannot auto-integrate",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy._requires_owner",
        evidence=(
            "_requires_owner(): intent.changes_scientific_authority → True → OWNER_GATE; "
            "CLAUDE.md: 'Do not mutate production DB/KG, activate taxonomy, publish scientific knowledge "
            "without required owner authorization'; "
            "scientific-authority changes require explicit owner review before integration"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="protection_spending_owner_gated",
        area="credential_scientific_protection",
        title="Spending is owner-gated — any spend_money intent blocks auto-integrate",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy._requires_owner",
        evidence=(
            "_requires_owner(): intent.spends_money → True → OWNER_GATE; "
            "PROTECTED_BOUNDARIES: 'new_spending': 'spending_provider_restoration'; "
            "no spending can be authorized autonomously — requires owner decision"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DRIFT_AND_COUPLING
    IntegrationPromotionCriterion(
        criterion_id="drift_material_fingerprint",
        area="drift_and_coupling",
        title="Material fingerprint — WorkIntent.material_fingerprint detects attribute drift",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.WorkIntent",
        evidence=(
            "WorkIntent.material_fingerprint: SHA-256 of JSON-serialized material attributes "
            "(head_sha, target_branch, risk_tier, reversible, provider_required, "
            "touches_production, changes_credentials, changes_scientific_authority, "
            "exposes_sensitive_locality, spends_money, destructive); "
            "fingerprint is stable for identical intents; any attribute change produces new fingerprint"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    IntegrationPromotionCriterion(
        criterion_id="drift_deployment_coupling_owner_gated",
        area="drift_and_coupling",
        title="Integration-to-main promotion is owner-gated — the promotion decision cannot be auto-triggered",
        status=IntegrationPromotionAuditStatus.OWNER_GATED,
        authoritative_module="app.autonomy.exception_policy.PROTECTED_BOUNDARIES",
        evidence=(
            "PROTECTED_BOUNDARIES['integration_main_promotion'] = 'integration_main_promotion'; "
            "evaluate_factory_gate(): target in {'main', 'master'} → OWNER_GATE; "
            "integration/main drift (promotion PRs from oc-autonomous-integration → main) "
            "requires explicit owner review, PR creation, merge authorization — "
            "no autonomous path from integration to main exists"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner must initiate and authorize integration-to-main promotion PR; cannot be autonomous",
    ),
    IntegrationPromotionCriterion(
        criterion_id="drift_sensitive_locality_owner_gated",
        area="drift_and_coupling",
        title="Sensitive locality exposure is owner-gated — location data cannot be integrated autonomously",
        status=IntegrationPromotionAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy._requires_owner",
        evidence=(
            "_requires_owner(): intent.exposes_sensitive_locality → True → OWNER_GATE; "
            "PROTECTED_BOUNDARIES: 'sensitive_locality': 'sensitive_locality'; "
            "CLAUDE.md: 'disclose sensitive locality' is an owner-governed boundary"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
)


@dataclass
class IntegrationPromotionAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[IntegrationPromotionCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[IntegrationPromotionCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[IntegrationPromotionCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(IntegrationPromotionAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(IntegrationPromotionAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(IntegrationPromotionAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(IntegrationPromotionAuditStatus.OWNER_GATED))

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


def get_integration_promotion_audit() -> IntegrationPromotionAudit:
    return IntegrationPromotionAudit(criteria=list(INTEGRATION_PROMOTION_CRITERIA))


def get_criteria_by_status(status: str) -> list[IntegrationPromotionCriterion]:
    return [c for c in INTEGRATION_PROMOTION_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[IntegrationPromotionCriterion]:
    return [c for c in INTEGRATION_PROMOTION_CRITERIA if c.area == area]


def get_gaps() -> list[IntegrationPromotionCriterion]:
    return get_criteria_by_status(IntegrationPromotionAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in INTEGRATION_PROMOTION_CRITERIA
        if c.next_action
    ]
