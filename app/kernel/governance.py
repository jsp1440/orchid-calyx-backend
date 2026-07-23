"""Policy and governance models for the Scientific Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class PolicyEffect(str, Enum):
    """Decision produced when a policy is evaluated."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_REVIEW = "require_review"


class PolicyStatus(str, Enum):
    """Lifecycle states for governance policy objects."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class GovernanceAction(str, Enum):
    """Canonical actions governed by Kernel policy."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    PUBLISH = "publish"
    COMMIT = "commit"
    REJECT = "reject"
    SUPERSEDE = "supersede"
    QUERY = "query"
    EXECUTE = "execute"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class GovernancePolicy(ScientificObject):
    """Immutable rule governing one or more scientific operations."""

    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.KNOWLEDGE_OBJECT))
    object_type: str = "governance_policy"
    name: str = ""
    description: str = ""
    actions: tuple[GovernanceAction, ...] = field(default_factory=tuple)
    effect: PolicyEffect = PolicyEffect.DENY
    status: PolicyStatus = PolicyStatus.DRAFT
    priority: int = 100
    conditions: Mapping[str, Any] = field(default_factory=dict)
    authored_by: str | None = None
    reviewed_by: str | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    supersedes_policy_ocid: OCID | None = None

    def __post_init__(self) -> None:
        ScientificObject.__post_init__(self)
        if self.ocid.kind is not OCIDKind.KNOWLEDGE_OBJECT:
            raise ScientificObjectValidationError(
                "governance policy requires a KNOWLEDGE_OBJECT OCID"
            )

        name = self.name.strip()
        description = self.description.strip()
        actions = tuple(self.actions)
        authored_by = self.authored_by.strip() if self.authored_by else None
        reviewed_by = self.reviewed_by.strip() if self.reviewed_by else None
        effective_from = _normalize_datetime(self.effective_from, "effective_from")
        effective_until = _normalize_datetime(self.effective_until, "effective_until")

        if not name:
            raise ScientificObjectValidationError("governance policy name must not be empty")
        if not actions:
            raise ScientificObjectValidationError(
                "governance policy requires at least one governed action"
            )
        if len(set(actions)) != len(actions):
            raise ScientificObjectValidationError(
                "governance policy actions must be unique"
            )
        if self.priority < 0:
            raise ScientificObjectValidationError("governance policy priority must be non-negative")
        if effective_from and effective_until and effective_until <= effective_from:
            raise ScientificObjectValidationError(
                "effective_until must be later than effective_from"
            )
        if self.status is PolicyStatus.ACTIVE and not authored_by:
            raise ScientificObjectValidationError(
                "active governance policies require authored_by"
            )
        if self.status in {PolicyStatus.ACTIVE, PolicyStatus.RETIRED, PolicyStatus.SUPERSEDED} and not reviewed_by:
            raise ScientificObjectValidationError(
                f"{self.status.value} governance policies require reviewed_by"
            )
        if self.status is PolicyStatus.SUPERSEDED and self.supersedes_policy_ocid is None:
            raise ScientificObjectValidationError(
                "superseded governance policies require supersedes_policy_ocid"
            )
        if (
            self.supersedes_policy_ocid is not None
            and self.supersedes_policy_ocid.kind is not OCIDKind.KNOWLEDGE_OBJECT
        ):
            raise ScientificObjectValidationError(
                "supersedes_policy_ocid must use a KNOWLEDGE_OBJECT OCID"
            )
        if self.supersedes_policy_ocid == self.ocid:
            raise ScientificObjectValidationError("governance policy cannot supersede itself")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "authored_by", authored_by)
        object.__setattr__(self, "reviewed_by", reviewed_by)
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "effective_until", effective_until)
        object.__setattr__(self, "conditions", MappingProxyType(dict(self.conditions)))


@dataclass(frozen=True, slots=True)
class GovernanceRequest:
    """Immutable policy-evaluation request."""

    action: GovernanceAction
    actor: str | None = None
    subject_ocid: OCID | None = None
    publication_ocid: OCID | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        actor = self.actor.strip() if self.actor else None
        if self.publication_ocid is not None and self.publication_ocid.kind is not OCIDKind.PUBLICATION:
            raise ScientificObjectValidationError(
                "publication_ocid must use a PUBLICATION OCID"
            )
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    """Immutable result of policy evaluation."""

    effect: PolicyEffect
    policy_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        policy_ocids = tuple(self.policy_ocids)
        reasons = tuple(reason.strip() for reason in self.reasons if reason.strip())
        if len(set(policy_ocids)) != len(policy_ocids):
            raise ScientificObjectValidationError(
                "governance decision policy_ocids must be unique"
            )
        if any(ocid.kind is not OCIDKind.KNOWLEDGE_OBJECT for ocid in policy_ocids):
            raise ScientificObjectValidationError(
                "governance decision policy_ocids must use KNOWLEDGE_OBJECT OCIDs"
            )
        evaluated_at = _normalize_datetime(self.evaluated_at, "evaluated_at")
        object.__setattr__(self, "policy_ocids", policy_ocids)
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(self, "evaluated_at", evaluated_at)


def _normalize_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScientificObjectValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
