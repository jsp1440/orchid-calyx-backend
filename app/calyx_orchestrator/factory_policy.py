from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum


class RiskTier(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    OWNER_GATED = "owner_gated"


class CheckerVerdict(StrEnum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class FactoryAction(StrEnum):
    REQUIRE_CHECKER = "require_checker"
    AUTO_INTEGRATE = "auto_integrate"
    PREPARE_REPAIR = "prepare_repair"
    PARK_PROVIDER_REQUIRED = "park_provider_required"
    OWNER_GATE = "owner_gate"


class MissionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    BLOCKED = "blocked"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class WorkIntent:
    repository: str
    issue_number: int
    head_sha: str
    target_branch: str
    risk_tier: RiskTier = RiskTier.LOW
    reversible: bool = True
    provider_required: bool = False
    touches_production: bool = False
    changes_credentials: bool = False
    changes_scientific_authority: bool = False
    exposes_sensitive_locality: bool = False
    spends_money: bool = False
    destructive: bool = False

    @property
    def material_fingerprint(self) -> str:
        material = {
            "changes_credentials": self.changes_credentials,
            "changes_scientific_authority": self.changes_scientific_authority,
            "destructive": self.destructive,
            "exposes_sensitive_locality": self.exposes_sensitive_locality,
            "head_sha": self.head_sha,
            "issue_number": self.issue_number,
            "provider_required": self.provider_required,
            "repository": self.repository,
            "reversible": self.reversible,
            "risk_tier": self.risk_tier.value,
            "spends_money": self.spends_money,
            "target_branch": self.target_branch,
            "touches_production": self.touches_production,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    maker_id: str
    checker_id: str | None = None
    checker_verdict: CheckerVerdict = CheckerVerdict.PENDING
    exact_head_verified: bool = False
    required_checks_passed: bool = False

    @property
    def independent_checker(self) -> bool:
        return bool(self.checker_id) and self.checker_id != self.maker_id


@dataclass(frozen=True, slots=True)
class FactoryDecision:
    action: FactoryAction
    reason: str
    fingerprint: str
    integration_authorized: bool = False


@dataclass(frozen=True, slots=True)
class MissionState:
    mission_id: str
    issue_number: int
    status: MissionStatus
    fingerprint: str
    attempt_count: int = 0
    maker_id: str | None = None
    checker_id: str | None = None
    last_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.mission_id.strip():
            raise ValueError("MISSION_ID_REQUIRED")
        if self.issue_number <= 0:
            raise ValueError("ISSUE_NUMBER_INVALID")
        if self.attempt_count < 0:
            raise ValueError("ATTEMPT_COUNT_INVALID")
        if not self.fingerprint.strip():
            raise ValueError("FINGERPRINT_REQUIRED")


def evaluate_factory_gate(
    intent: WorkIntent,
    evidence: ValidationEvidence,
    *,
    no_api_mode: bool = True,
) -> FactoryDecision:
    """Decide whether one bounded change can advance without owner intervention.

    This gate is intentionally narrower than a merge/deploy authority system. It may
    authorize integration only into a non-main integration branch after independent
    checker success and exact-head validation. Main, production, credentials,
    spending, destructive operations, scientific-authority changes, and sensitive
    locality remain owner-gated.
    """

    fingerprint = intent.material_fingerprint

    if _requires_owner(intent):
        return FactoryDecision(
            action=FactoryAction.OWNER_GATE,
            reason="OWNER_GOVERNED_BOUNDARY",
            fingerprint=fingerprint,
        )

    if intent.provider_required and no_api_mode:
        return FactoryDecision(
            action=FactoryAction.PARK_PROVIDER_REQUIRED,
            reason="NO_API_PROVIDER_WORK_PARKED",
            fingerprint=fingerprint,
        )

    if not evidence.independent_checker:
        return FactoryDecision(
            action=FactoryAction.REQUIRE_CHECKER,
            reason="INDEPENDENT_CHECKER_REQUIRED",
            fingerprint=fingerprint,
        )

    if not evidence.exact_head_verified:
        return FactoryDecision(
            action=FactoryAction.REQUIRE_CHECKER,
            reason="EXACT_HEAD_VALIDATION_REQUIRED",
            fingerprint=fingerprint,
        )

    if evidence.checker_verdict is CheckerVerdict.FAIL:
        return FactoryDecision(
            action=FactoryAction.PREPARE_REPAIR,
            reason="CHECKER_REJECTED_CHANGE",
            fingerprint=fingerprint,
        )

    if evidence.checker_verdict in {
        CheckerVerdict.PENDING,
        CheckerVerdict.INCONCLUSIVE,
    }:
        return FactoryDecision(
            action=FactoryAction.REQUIRE_CHECKER,
            reason=f"CHECKER_{evidence.checker_verdict.value.upper()}",
            fingerprint=fingerprint,
        )

    if not evidence.required_checks_passed:
        return FactoryDecision(
            action=FactoryAction.REQUIRE_CHECKER,
            reason="REQUIRED_CHECKS_NOT_PROVEN",
            fingerprint=fingerprint,
        )

    if intent.risk_tier in {RiskTier.HIGH, RiskTier.OWNER_GATED}:
        return FactoryDecision(
            action=FactoryAction.OWNER_GATE,
            reason=f"RISK_TIER_{intent.risk_tier.value.upper()}_REQUIRES_OWNER",
            fingerprint=fingerprint,
        )

    return FactoryDecision(
        action=FactoryAction.AUTO_INTEGRATE,
        reason="INDEPENDENT_VALIDATION_PASSED_SAFE_INTEGRATION",
        fingerprint=fingerprint,
        integration_authorized=True,
    )


def _requires_owner(intent: WorkIntent) -> bool:
    target = intent.target_branch.strip().lower()
    return any(
        (
            target in {"main", "master"},
            intent.touches_production,
            intent.changes_credentials,
            intent.changes_scientific_authority,
            intent.exposes_sensitive_locality,
            intent.spends_money,
            intent.destructive,
            not intent.reversible,
        )
    )
