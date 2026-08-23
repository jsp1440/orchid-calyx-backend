"""Shared constituent, membership, preference, and communication policy foundation."""

from .domain import (
    AudienceMember,
    CommunicationState,
    ConstituentKind,
    MembershipStatus,
    MessagePurpose,
    PreferenceState,
    approval_required,
    assert_authorization_source,
    audience_snapshot_sha256,
    normalize_auth_subject,
    normalize_email,
    recipient_delivery_decision,
    validate_state_transition,
)

__all__ = [
    "AudienceMember",
    "CommunicationState",
    "ConstituentKind",
    "MembershipStatus",
    "MessagePurpose",
    "PreferenceState",
    "approval_required",
    "assert_authorization_source",
    "audience_snapshot_sha256",
    "normalize_auth_subject",
    "normalize_email",
    "recipient_delivery_decision",
    "validate_state_transition",
]
