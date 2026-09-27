"""Fail-closed domain contracts for Orchid Continuum constituents and communications."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID


class ConstituentKind(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"


class MembershipStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    GRACE = "grace"
    LAPSED = "lapsed"
    CANCELLED = "cancelled"


class PreferenceState(str, Enum):
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    REQUIRED_SERVICE = "required_service"


class SuppressionKind(str, Enum):
    UNSUBSCRIBE = "unsubscribe"
    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    INVALID = "invalid"
    ADMIN_BLOCK = "admin_block"


class MessagePurpose(str, Enum):
    TRANSACTIONAL = "transactional"
    MEMBERSHIP_RELATIONSHIP = "membership_relationship"
    RESEARCH_DELIVERY = "research_delivery"
    COMMUNITY = "community"
    FUNDRAISING = "fundraising"
    MARKETING = "marketing"
    SUPPORT = "support"
    ADMINISTRATIVE = "administrative"


class CommunicationState(str, Enum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SENDING = "sending"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    CANCELLED = "cancelled"


BROADCAST_APPROVAL_PURPOSES = frozenset(
    {
        MessagePurpose.COMMUNITY,
        MessagePurpose.FUNDRAISING,
        MessagePurpose.MARKETING,
    }
)

REQUIRED_SERVICE_PURPOSES = frozenset(
    {
        MessagePurpose.TRANSACTIONAL,
        MessagePurpose.SUPPORT,
        MessagePurpose.ADMINISTRATIVE,
    }
)

CRITICAL_SUPPRESSIONS = frozenset(
    {
        SuppressionKind.HARD_BOUNCE,
        SuppressionKind.COMPLAINT,
        SuppressionKind.INVALID,
        SuppressionKind.ADMIN_BLOCK,
    }
)

UNTRUSTED_AUTHORIZATION_SOURCES = frozenset(
    {
        "email_gateway",
        "inbound_email",
        "untrusted_content",
    }
)

_ALLOWED_TRANSITIONS: dict[CommunicationState, frozenset[CommunicationState]] = {
    CommunicationState.DRAFT: frozenset(
        {CommunicationState.AWAITING_APPROVAL, CommunicationState.CANCELLED}
    ),
    CommunicationState.AWAITING_APPROVAL: frozenset(
        {CommunicationState.APPROVED, CommunicationState.CANCELLED}
    ),
    CommunicationState.APPROVED: frozenset(
        {CommunicationState.SENDING, CommunicationState.CANCELLED}
    ),
    CommunicationState.SENDING: frozenset(
        {CommunicationState.COMPLETED, CommunicationState.PARTIALLY_FAILED}
    ),
    CommunicationState.PARTIALLY_FAILED: frozenset(
        {CommunicationState.SENDING, CommunicationState.CANCELLED}
    ),
    CommunicationState.COMPLETED: frozenset(),
    CommunicationState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class AudienceMember:
    constituent_id: int
    normalized_email: str
    allowed: bool
    decision_reason: str


def normalize_email(value: str) -> str:
    """Normalize an email address without silently accepting malformed input."""

    normalized = value.strip().lower()
    if not normalized or len(normalized) > 320 or any(char.isspace() for char in normalized):
        raise ValueError("INVALID_EMAIL")
    if normalized.count("@") != 1:
        raise ValueError("INVALID_EMAIL")
    local, domain = normalized.split("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("INVALID_EMAIL")
    return normalized


def normalize_auth_subject(value: str) -> str:
    """Canonicalize a stable external auth subject without importing profile metadata."""

    raw = value.strip()
    if ":" not in raw:
        raise ValueError("AUTH_SUBJECT_PROVIDER_REQUIRED")
    provider, subject = raw.split(":", 1)
    provider = provider.strip().lower()
    subject = subject.strip()
    if not provider or not subject:
        raise ValueError("INVALID_AUTH_SUBJECT")
    if provider == "supabase":
        try:
            subject = str(UUID(subject))
        except ValueError as exc:
            raise ValueError("INVALID_SUPABASE_SUBJECT") from exc
    return f"{provider}:{subject}"


def approval_required(purpose: MessagePurpose, audience_size: int) -> bool:
    """Require human approval for campaigns and conservatively for any multi-recipient send."""

    if audience_size < 1:
        raise ValueError("AUDIENCE_REQUIRED")
    return purpose in BROADCAST_APPROVAL_PURPOSES or audience_size > 1


def recipient_delivery_decision(
    *,
    purpose: MessagePurpose,
    preference: PreferenceState | None,
    suppressions: set[SuppressionKind] | frozenset[SuppressionKind],
) -> tuple[bool, str]:
    """Apply delivery-critical suppression before purpose-specific preference state."""

    if CRITICAL_SUPPRESSIONS.intersection(suppressions):
        return False, "critical_suppression"
    if SuppressionKind.UNSUBSCRIBE in suppressions and purpose not in REQUIRED_SERVICE_PURPOSES:
        return False, "unsubscribed"
    if purpose in REQUIRED_SERVICE_PURPOSES:
        return True, "required_service_purpose"
    if preference is PreferenceState.REQUIRED_SERVICE:
        return True, "required_service_preference"
    if preference is PreferenceState.SUBSCRIBED:
        return True, "subscribed"
    if preference is PreferenceState.UNSUBSCRIBED:
        return False, "unsubscribed"
    return False, "no_affirmative_preference"


def assert_authorization_source(source_kind: str) -> None:
    """Inbound or otherwise untrusted content can never authorize outbound contact."""

    normalized = source_kind.strip().lower()
    if not normalized or normalized in UNTRUSTED_AUTHORIZATION_SOURCES:
        raise ValueError("UNTRUSTED_OUTBOUND_AUTHORIZATION_SOURCE")


def validate_state_transition(
    current: CommunicationState,
    target: CommunicationState,
    *,
    audience_frozen: bool,
    approval_recorded: bool = False,
) -> None:
    """Validate the communication state machine and its approval boundary."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"INVALID_COMMUNICATION_TRANSITION:{current.value}->{target.value}")
    if target is CommunicationState.AWAITING_APPROVAL and not audience_frozen:
        raise ValueError("FROZEN_AUDIENCE_REQUIRED")
    if target is CommunicationState.APPROVED:
        if not audience_frozen:
            raise ValueError("FROZEN_AUDIENCE_REQUIRED")
        if not approval_recorded:
            raise ValueError("APPROVAL_RECORD_REQUIRED")


def audience_snapshot_sha256(members: list[AudienceMember]) -> str:
    """Hash the exact frozen recipient decisions so approval binds to one audience."""

    if not members:
        raise ValueError("AUDIENCE_REQUIRED")
    canonical = [
        {
            "allowed": item.allowed,
            "constituent_id": item.constituent_id,
            "decision_reason": item.decision_reason,
            "normalized_email": normalize_email(item.normalized_email),
        }
        for item in members
    ]
    canonical.sort(key=lambda item: (item["constituent_id"], item["normalized_email"]))
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Society membership lifecycle
# ---------------------------------------------------------------------------

_MEMBERSHIP_TRANSITIONS: dict[MembershipStatus, frozenset[MembershipStatus]] = {
    MembershipStatus.PENDING: frozenset({MembershipStatus.ACTIVE, MembershipStatus.CANCELLED}),
    MembershipStatus.ACTIVE: frozenset(
        {MembershipStatus.GRACE, MembershipStatus.LAPSED, MembershipStatus.CANCELLED}
    ),
    MembershipStatus.GRACE: frozenset(
        {MembershipStatus.ACTIVE, MembershipStatus.LAPSED, MembershipStatus.CANCELLED}
    ),
    MembershipStatus.LAPSED: frozenset({MembershipStatus.ACTIVE, MembershipStatus.CANCELLED}),
    # Reinstating a cancelled membership is allowed, but only with a recorded reason.
    MembershipStatus.CANCELLED: frozenset({MembershipStatus.ACTIVE}),
}


def validate_membership_transition(
    current: MembershipStatus,
    target: MembershipStatus,
    *,
    reason: str | None = None,
) -> None:
    """Fail closed on membership status changes outside the documented lifecycle."""

    if target not in _MEMBERSHIP_TRANSITIONS[current]:
        raise ValueError(f"INVALID_MEMBERSHIP_TRANSITION:{current.value}->{target.value}")
    needs_reason = target is MembershipStatus.CANCELLED or current is MembershipStatus.CANCELLED
    if needs_reason and not (reason and reason.strip()):
        raise ValueError("MEMBERSHIP_TRANSITION_REASON_REQUIRED")


def add_months(value: datetime, months: int) -> datetime:
    """Calendar month arithmetic, clamping to the last day of a shorter month."""

    if months < 1:
        raise ValueError("INVALID_MEMBERSHIP_TERM")
    index = value.month - 1 + months
    year = value.year + index // 12
    month = index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def lifecycle_status_at(
    status: MembershipStatus,
    expires_at: datetime | None,
    grace_days: int,
    as_of: datetime,
) -> MembershipStatus:
    """The status time alone implies: active -> grace at expiry, grace -> lapsed after grace.

    Pending, lapsed and cancelled memberships never change by the passage of time.
    """

    if expires_at is None or status not in (MembershipStatus.ACTIVE, MembershipStatus.GRACE):
        return status
    if as_of < expires_at:
        return status
    if as_of < expires_at + timedelta(days=grace_days):
        return MembershipStatus.GRACE
    return MembershipStatus.LAPSED


def renewal_term(
    status: MembershipStatus,
    expires_at: datetime | None,
    term_months: int,
    as_of: datetime,
) -> tuple[datetime, datetime]:
    """(new_starts_at, new_expires_at) for one renewal.

    Active and grace memberships renew from their existing expiry, so paying early
    never loses time and paying during grace keeps the anniversary. Pending, lapsed
    and cancelled memberships start a new term at ``as_of``.
    """

    if status in (MembershipStatus.ACTIVE, MembershipStatus.GRACE) and expires_at is not None:
        base = expires_at
    else:
        base = as_of
    return base, add_months(base, term_months)


SOCIETY_ENTITLEMENT_PREFIX = "society."


def validate_society_entitlement_code(code: str) -> str:
    """Society membership may only grant society-scoped entitlements.

    Private Conservatory, OASIS, Calyx, research, donor, restricted-locality and
    collection access can never be conferred by a society membership level.
    """

    normalized = code.strip().lower()
    if not normalized.startswith(SOCIETY_ENTITLEMENT_PREFIX) or not re.fullmatch(
        r"society\.[a-z0-9_]{1,60}", normalized
    ):
        raise ValueError(f"FORBIDDEN_SOCIETY_ENTITLEMENT:{code}")
    return normalized
