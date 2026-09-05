from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ExceptionClass = Literal[
    "none",
    "informational",
    "engineering_exception",
    "owner_exception",
]

OwnerExceptionCategory = Literal[
    "governance",
    "scientific_activation",
    "sensitive_locality",
    "credential_security",
    "spending_provider_restoration",
    "destructive_irreversible",
    "production_activation",
    "integration_main_promotion",
]

ENGINEERING_ANOMALIES = frozenset(
    {
        "queue_backoff_contradiction",
        "exact_head_ci_failure",
        "exact_head_ci_error",
        "exact_head_ci_skipped",
        "stale_lease",
        "orphan_lease",
        "duplicate_fingerprint",
        "repair_backoff_contradiction",
        "provider_disabled",
        "lane_blocked",
    }
)

PROTECTED_BOUNDARIES: dict[str, OwnerExceptionCategory] = {
    "governance_change": "governance",
    "scientific_activation": "scientific_activation",
    "scientific_provenance_mutation": "scientific_activation",
    "sensitive_locality_disclosure": "sensitive_locality",
    "sensitive_locality_policy_change": "sensitive_locality",
    "credential_change": "credential_security",
    "security_authority_change": "credential_security",
    "paid_provider_restoration": "spending_provider_restoration",
    "new_spending": "spending_provider_restoration",
    "destructive_operation": "destructive_irreversible",
    "irreversible_operation": "destructive_irreversible",
    "production_activation": "production_activation",
    "production_health_decision": "production_activation",
    "integration_main_promotion": "integration_main_promotion",
}


@dataclass(frozen=True, slots=True)
class ExceptionDecision:
    exception_class: ExceptionClass
    owner_decision_required: bool
    owner_exception_category: OwnerExceptionCategory | None
    autonomous_repair_available: bool
    independent_authorized_work_available: bool
    should_interrupt_owner: bool
    action: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_exception(
    anomaly: str | None,
    *,
    protected_boundary: str | None = None,
    autonomous_repair_available: bool = False,
    independent_authorized_work_available: bool = False,
    deterministic_work_available: bool = False,
) -> ExceptionDecision:
    """Classify a completion anomaly without conflating detection with escalation.

    Owner interruption is permitted only when an owner-only protected boundary is
    the actual blocker and neither bounded repair nor independent authorized work
    can continue. Provider-disabled state remains an engineering exception while
    deterministic/no-API work is available.
    """

    independent_work = independent_authorized_work_available or deterministic_work_available

    if not anomaly and not protected_boundary:
        return ExceptionDecision(
            exception_class="none",
            owner_decision_required=False,
            owner_exception_category=None,
            autonomous_repair_available=False,
            independent_authorized_work_available=independent_work,
            should_interrupt_owner=False,
            action="continue",
        )

    category = PROTECTED_BOUNDARIES.get(protected_boundary or "")
    if category is not None:
        blocked = not autonomous_repair_available and not independent_work
        return ExceptionDecision(
            exception_class="owner_exception" if blocked else "engineering_exception",
            owner_decision_required=blocked,
            owner_exception_category=category if blocked else None,
            autonomous_repair_available=autonomous_repair_available,
            independent_authorized_work_available=independent_work,
            should_interrupt_owner=blocked,
            action="interrupt_owner" if blocked else "repair_or_continue_other_work",
        )

    if anomaly == "provider_disabled" and deterministic_work_available:
        return ExceptionDecision(
            exception_class="engineering_exception",
            owner_decision_required=False,
            owner_exception_category=None,
            autonomous_repair_available=False,
            independent_authorized_work_available=True,
            should_interrupt_owner=False,
            action="park_provider_and_continue_deterministic_work",
        )

    if anomaly in ENGINEERING_ANOMALIES:
        return ExceptionDecision(
            exception_class="engineering_exception",
            owner_decision_required=False,
            owner_exception_category=None,
            autonomous_repair_available=autonomous_repair_available,
            independent_authorized_work_available=independent_work,
            should_interrupt_owner=False,
            action=(
                "repair"
                if autonomous_repair_available
                else "continue_other_authorized_work"
                if independent_work
                else "park_and_reconcile"
            ),
        )

    return ExceptionDecision(
        exception_class="informational",
        owner_decision_required=False,
        owner_exception_category=None,
        autonomous_repair_available=autonomous_repair_available,
        independent_authorized_work_available=independent_work,
        should_interrupt_owner=False,
        action="observe_and_continue",
    )
