from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from app.calyx_orchestrator.head_bound_integration import (
    EvidenceSource,
    IntegrationEvidence,
    Observation,
    same_actor,
)
from app.calyx_orchestrator.head_bound_integration import (
    exact_head_verified as head_bound_exact_head_verified,
)


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


#: One rule, imported rather than restated. What stood here was a SEPARATE
#: implementation that happened to agree -- a `(str, str) -> bool` predicate
#: beside the module's `(str) -> str` normaliser -- and agreeing is exactly the
#: problem, because nothing made it keep agreeing. (Not "identical": an
#: independent check diffed them, and this comment asserted the same falsehood
#: its sibling in `head_bound_integration` had already been corrected for, in
#: the same commit.)
_same_actor = same_actor


def _head_bound_verified(
    *,
    head_sha: str,
    checker_head_sha: str,
    checks_head_sha: str,
    maker_id: str,
    checker_id: str | None,
) -> bool:
    """Ask `head_bound_integration` whether these heads verify this one.

    Built as observations so the single rule applies: a head that is not a full
    commit id cannot be CONSTRUCTED into one, and a checker who is the maker is
    not independent.

    There is deliberately no local `_is_full_sha` pre-filter. One stood here and
    a mutation sweep showed it could be degraded to `bool(value)` -- accepting
    any string at all -- with the whole suite still green, because every head it
    screened is screened again, harder, by the constructors below. A guard whose
    removal changes no outcome is not a second line of defence; it is a second
    copy of a rule, free to drift from the one that is actually enforced.
    """
    try:
        evidence = IntegrationEvidence(
            head_sha=head_sha,
            maker_id=maker_id,
            checks=Observation(
                source=EvidenceSource.REQUIRED_CHECKS,
                head_sha=checks_head_sha,
                passed=True,
                observer_id="required-checks",
            ),
            review=Observation(
                source=EvidenceSource.INDEPENDENT_CHECKER,
                head_sha=checker_head_sha,
                passed=True,
                observer_id=checker_id or "",
            ),
        )
    except ValueError:
        return False
    return head_bound_exact_head_verified(evidence)


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
    """What is known about one change, and which commit each fact is about.

    `exact_head_verified` used to be a bare boolean the caller asserted, and
    `checker_dispatch` derived it by comparing the checker's head against the
    head recorded in the ASSIGNMENT. Both are satisfied by a stale head: if the
    pull request moves after the assignment is written, the checker still
    verified the assignment's head, the boolean is still true, and this gate
    still says AUTO_INTEGRATE for a commit nobody checked. Three pull requests
    in this repository merged that way.

    So the head fields are recorded instead, and the boolean is DERIVED from
    them by `head_bound_integration`. `exact_head_verified` remains as a
    property so existing readers keep working, but nothing can set it any more.
    """

    maker_id: str
    checker_id: str | None = None
    checker_verdict: CheckerVerdict = CheckerVerdict.PENDING
    required_checks_passed: bool = False
    #: The pull request head as observed NOW -- the commit that would merge.
    head_sha: str = ""
    #: The head the independent checker actually verified.
    checker_head_sha: str = ""
    #: The head the required checks actually ran against.
    checks_head_sha: str = ""

    @property
    def independent_checker(self) -> bool:
        """One actor, one identity, however they spelled it.

        This compared raw strings, so `"maker-a "` counted as a different actor
        from `"maker-a"` and a maker could certify their own work by adding a
        space. The head-bound rule normalizes, and two rules that disagree about
        who someone is will eventually disagree about whether anyone checked.

        `strip()` on the emptiness test for the same reason: `bool("   ")` is
        true, so a checker id of three spaces reported an independent checker
        here while `decide_next_step` -- which does strip -- refused the very
        same record. Whitespace is not a person.

        `checker_id` is `str | None`, and the first version of that fix called
        `.strip()` on it directly -- which turns "nobody has checked this yet",
        the commonest state a pending record is in, into an AttributeError
        inside the gate. Absence is not an error; it is a no.
        """
        checker_id = self.checker_id or ""
        return bool(checker_id.strip()) and not _same_actor(checker_id, self.maker_id)

    @property
    def exact_head_verified(self) -> bool:
        """Whether the checker and the required checks both name this exact head.

        Delegated to `head_bound_integration`, which is the rule. Two copies of
        one rule drift: an independent check found this property degradable to a
        7-hex prefix comparison with the whole suite green, because the prefix
        test had been written against the module and this was the copy the merge
        path actually read.

        Absence is not agreement: an unrecorded head is the empty string, which
        equals no commit, so a record that cannot say which commit it is about
        can never satisfy this.
        """
        return _head_bound_verified(
            head_sha=self.head_sha,
            checker_head_sha=self.checker_head_sha,
            checks_head_sha=self.checks_head_sha,
            maker_id=self.maker_id,
            checker_id=self.checker_id,
        )

    @property
    def stale_evidence(self) -> tuple[str, ...]:
        """Which facts are about some other commit, for a refusal that can say so."""
        stale: list[str] = []
        if self.checker_head_sha and self.checker_head_sha != self.head_sha:
            stale.append(f"checker verified {self.checker_head_sha[:12]}")
        if self.checks_head_sha and self.checks_head_sha != self.head_sha:
            stale.append(f"checks ran against {self.checks_head_sha[:12]}")
        return tuple(stale)


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

    if evidence.head_sha != intent.head_sha:
        # Named, not bare. `EXACT_HEAD_VALIDATION_REQUIRED` was replaced for
        # exactly this: a refusal that cannot say which commit it is about
        # reads as "nobody checked" when the truth is "somebody checked
        # something else", and this whole lineage exists because of that
        # confusion. A new gate gets the same treatment as the ones it stands
        # beside.
        return FactoryDecision(
            action=FactoryAction.REQUIRE_CHECKER,
            reason=(
                "INTENT_HEAD_MISMATCH: authorized for "
                f"{intent.head_sha[:12] or 'no recorded head'}, evidence is about "
                f"{evidence.head_sha[:12] or 'no recorded head'}"
            ),
            fingerprint=fingerprint,
        )

    if not evidence.independent_checker:
        return FactoryDecision(
            action=FactoryAction.REQUIRE_CHECKER,
            reason="INDEPENDENT_CHECKER_REQUIRED",
            fingerprint=fingerprint,
        )

    if not evidence.exact_head_verified:
        stale = evidence.stale_evidence
        reason = (
            f"EVIDENCE_IS_ABOUT_ANOTHER_HEAD: {'; '.join(stale)}"
            if stale
            else "EXACT_HEAD_VALIDATION_REQUIRED"
        )
        return FactoryDecision(
            action=FactoryAction.REQUIRE_CHECKER,
            reason=reason,
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
