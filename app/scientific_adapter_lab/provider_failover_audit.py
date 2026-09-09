"""Provider failover audit — Approved Task Priority 32.

Verify Claude/Gemini/OpenAI fallback is bounded, fail-closed on security,
redacted, non-thrashing, and provider-independent in governance.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "provider-failover-audit/v1"
AUDIT_DATE = "2026-09-09"


class ProviderFailoverAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class ProviderFailoverCriterion:
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


PROVIDER_FAILOVER_CRITERIA: tuple[ProviderFailoverCriterion, ...] = (

    # ------------------------------------------------------------------ BOUNDED_FALLBACK
    ProviderFailoverCriterion(
        criterion_id="bounded_park_provider_required",
        area="bounded_fallback",
        title="Park-provider required — provider dependency parks task rather than silently degrading",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.event_continuation.ContinuationAction",
        evidence=(
            "ContinuationAction.PARK_PROVIDER_REQUIRED = 'park_provider_required'; "
            "ContinuationAction.CONTINUE_PROVIDER_FREE = 'continue_provider_free'; "
            "_park_provider_required(): returns PARK_PROVIDER_REQUIRED with "
            "code 'NO_API_PROVIDER_CONTINUATION_PARKED' or 'PROVIDER_CONTINUATION_REQUIRES_SEPARATE_AUTHORIZATION'; "
            "provider-required tasks park, not silently degrade"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="bounded_provider_free_path",
        area="bounded_fallback",
        title="Provider-free continuation — deterministic work continues without provider on park",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.event_continuation.ContinuationAction",
        evidence=(
            "event_continuation.py: active_policy.provider_required is False → "
            "action=ContinuationAction.CONTINUE_PROVIDER_FREE; "
            "exception_policy: anomaly='provider_disabled' and deterministic_work_available → "
            "action='park_provider_and_continue_deterministic_work'; "
            "non-provider tasks advance while provider tasks are parked"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="bounded_factory_park",
        area="bounded_fallback",
        title="Factory gate park — factory_policy parks provider-dependent missions",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_policy.FactoryAction",
        evidence=(
            "FactoryAction.PARK_PROVIDER_REQUIRED = 'park_provider_required'; "
            "factory_bridge.py: PARK_PROVIDER_REQUIRED when provider check fails; "
            "factory gate is the upstream check — provider-dependent missions cannot reach the queue "
            "without passing the factory gate"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ FAIL_CLOSED_SECURITY
    ProviderFailoverCriterion(
        criterion_id="fail_closed_no_api_mode",
        area="fail_closed_security",
        title="NO-API mode fail-closed — provider generative paths are blocked in NO-API mode",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.event_continuation",
        evidence=(
            "event_continuation._park_provider_required(): "
            "code 'NO_API_PROVIDER_CONTINUATION_PARKED' when NO-API mode active; "
            "event_continuation.py: provider_required → PARK_PROVIDER_REQUIRED; "
            "provider calls cannot proceed in NO-API mode — fail-closed, not fail-open"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="fail_closed_security_guard",
        area="fail_closed_security",
        title="Security guard not weakened — provider failover cannot disable Agent Security Guard",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="AGENTS.md",
        evidence=(
            "AGENTS.md: 'Do NOT weaken, bypass, disable, skip, delete, or make permissive the "
            "Agent Security Guard merely to obtain green CI'; "
            "CLAUDE.md: 'Do NOT weaken, remove, or bypass Agent Security Guard'; "
            "provider failover path cannot lower security posture — fail-closed invariant enforced by policy"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="fail_closed_provider_disabled_engineering",
        area="fail_closed_security",
        title="Provider-disabled is engineering exception — does not route to owner escalation unless all work blocked",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.autonomy.exception_policy.classify_exception",
        evidence=(
            "classify_exception('provider_disabled', deterministic_work_available=True): "
            "exception_class='engineering_exception', owner_decision_required=False, "
            "action='park_provider_and_continue_deterministic_work'; "
            "provider failure stays in engineering path while deterministic work remains available"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ REDACTION
    ProviderFailoverCriterion(
        criterion_id="redaction_credential_not_logged",
        area="redaction",
        title="Credential redaction — provider tokens are never logged or printed",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.github_proposal_mutation_adapter",
        evidence=(
            "github_proposal_mutation_adapter.__repr__(): "
            "'(base_url={self._base_url!r}, token=<redacted>)'; "
            "knowledge_source_registry: redacted_payload strips sensitive keys via _safe(); "
            "CLAUDE.md: 'No credential value may be requested, printed, logged, copied, or committed'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="redaction_provider_status_no_secrets",
        area="redaction",
        title="Provider status reports no secrets — provider health reports are redacted",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.scientific_adapter_lab.research_station_persistence_audit",
        evidence=(
            "research_station_persistence_audit: 'artifact content is hashed, not printed; "
            "secrets_exposed=False in provider status'; "
            "provider status: name, model, generative (bool), configuration (dict) — "
            "no credential value in status payload; "
            "vision_lexicon preflight: provider_status redacted from payload before response"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ NON_THRASHING
    ProviderFailoverCriterion(
        criterion_id="non_thrashing_park_not_retry",
        area="non_thrashing",
        title="Park not retry — provider failure parks the task, not immediate re-retry",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.event_continuation",
        evidence=(
            "PARK_PROVIDER_REQUIRED returns immediately with parking code — not a retry loop; "
            "refill(): REPAIR_BACKOFF and OWNER_GATED tasks not re-admitted; "
            "park_provider_and_continue_deterministic_work action in exception_policy: "
            "parks provider rather than spinning on retry"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="non_thrashing_live_failover_blocked",
        area="non_thrashing",
        title="Live Claude/Gemini/OpenAI failover blocked — NO-API mode prevents thrashing between providers",
        status=ProviderFailoverAuditStatus.BLOCKED,
        authoritative_module="app.calyx_orchestrator.event_continuation",
        evidence=(
            "NO-API mode prevents all generative provider calls (Claude, Gemini, OpenAI); "
            "provider_required tasks receive PARK_PROVIDER_REQUIRED with 'NO_API_PROVIDER_CONTINUATION_PARKED'; "
            "live provider switching cannot be tested without API mode active"
        ),
        gap_description=None,
        blocker_reason="NO-API mode is in force — live provider failover switching cannot be exercised",
        next_action="Lift NO-API constraint to verify live Claude/Gemini/OpenAI provider switching behavior",
    ),

    # ------------------------------------------------------------------ GOVERNANCE_INDEPENDENCE
    ProviderFailoverCriterion(
        criterion_id="governance_independent_of_provider",
        area="governance_independence",
        title="Governance independent of provider — owner gates and security rules do not depend on which provider is active",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.autonomy.exception_policy.PROTECTED_BOUNDARIES",
        evidence=(
            "PROTECTED_BOUNDARIES: 8 categories enforced regardless of provider identity; "
            "classify_exception(): provider_disabled anomaly → engineering_exception; "
            "protected_boundary categories (governance, scientific_activation, etc.) are provider-agnostic; "
            "AGENTS.md security constraints are model-agnostic — apply to Claude, Gemini, OpenAI alike"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="governance_owner_gate_no_provider_bypass",
        area="governance_independence",
        title="Owner gate cannot be bypassed by provider switch — owner gates are governance-level, not provider-level",
        status=ProviderFailoverAuditStatus.READY,
        authoritative_module="app.calyx_orchestrator.deep_orchestrate.DeepOrchestrate",
        evidence=(
            "DeepOrchestrate: OWNER_GATED tasks require authorize() call — not refill or provider swap; "
            "recover_from_backoff(): owner-gated leaf transitions to OWNER_GATED, not READY; "
            "owner gates are attached to authority_class, not provider identity; "
            "changing the provider cannot satisfy an owner gate"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    ProviderFailoverCriterion(
        criterion_id="governance_no_api_spending_required",
        area="governance_independence",
        title="Provider spending requires owner authorization — paid provider restoration is an owner exception",
        status=ProviderFailoverAuditStatus.OWNER_GATED,
        authoritative_module="app.autonomy.exception_policy.PROTECTED_BOUNDARIES",
        evidence=(
            "PROTECTED_BOUNDARIES: 'paid_provider_restoration': 'spending_provider_restoration'; "
            "'new_spending': 'spending_provider_restoration'; "
            "classify_exception(protected_boundary='paid_provider_restoration'): "
            "exception_class='owner_exception', owner_decision_required=True; "
            "no provider can be restored to paid operation without explicit owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before restoring any paid provider to production operation",
    ),
)


@dataclass
class ProviderFailoverAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[ProviderFailoverCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[ProviderFailoverCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[ProviderFailoverCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(ProviderFailoverAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(ProviderFailoverAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(ProviderFailoverAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(ProviderFailoverAuditStatus.OWNER_GATED))

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


def get_provider_failover_audit() -> ProviderFailoverAudit:
    return ProviderFailoverAudit(criteria=list(PROVIDER_FAILOVER_CRITERIA))


def get_criteria_by_status(status: str) -> list[ProviderFailoverCriterion]:
    return [c for c in PROVIDER_FAILOVER_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[ProviderFailoverCriterion]:
    return [c for c in PROVIDER_FAILOVER_CRITERIA if c.area == area]


def get_gaps() -> list[ProviderFailoverCriterion]:
    return get_criteria_by_status(ProviderFailoverAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in PROVIDER_FAILOVER_CRITERIA
        if c.next_action
    ]
