from __future__ import annotations

import pytest

from app.constituent_platform import (
    AudienceMember,
    CommunicationState,
    MessagePurpose,
    PreferenceState,
    SuppressionKind,
    approval_required,
    assert_authorization_source,
    audience_snapshot_sha256,
    normalize_auth_subject,
    normalize_email,
    recipient_delivery_decision,
    validate_state_transition,
)


def test_email_and_supabase_subject_are_canonicalized() -> None:
    assert normalize_email(" Jane.Example@Example.COM ") == "jane.example@example.com"
    assert (
        normalize_auth_subject("supabase:550E8400-E29B-41D4-A716-446655440000")
        == "supabase:550e8400-e29b-41d4-a716-446655440000"
    )


@pytest.mark.parametrize("value", ["", "missing-at", "a@@b.example", "a @b.example"])
def test_malformed_email_fails_closed(value: str) -> None:
    with pytest.raises(ValueError, match="INVALID_EMAIL"):
        normalize_email(value)


def test_stable_auth_subject_does_not_import_profile_metadata() -> None:
    assert normalize_auth_subject("custom-provider:opaque-user-42") == (
        "custom-provider:opaque-user-42"
    )
    with pytest.raises(ValueError, match="AUTH_SUBJECT_PROVIDER_REQUIRED"):
        normalize_auth_subject("opaque-user-42")


def test_campaign_and_multi_recipient_intents_require_approval() -> None:
    assert approval_required(MessagePurpose.MARKETING, 1) is True
    assert approval_required(MessagePurpose.COMMUNITY, 10) is True
    assert approval_required(MessagePurpose.TRANSACTIONAL, 2) is True
    assert approval_required(MessagePurpose.TRANSACTIONAL, 1) is False


def test_delivery_critical_suppression_overrides_required_service() -> None:
    allowed, reason = recipient_delivery_decision(
        purpose=MessagePurpose.TRANSACTIONAL,
        preference=PreferenceState.REQUIRED_SERVICE,
        suppressions={SuppressionKind.HARD_BOUNCE},
    )
    assert allowed is False
    assert reason == "critical_suppression"


def test_marketing_unsubscribe_does_not_silence_required_transactional_message() -> None:
    assert recipient_delivery_decision(
        purpose=MessagePurpose.MARKETING,
        preference=PreferenceState.SUBSCRIBED,
        suppressions={SuppressionKind.UNSUBSCRIBE},
    ) == (False, "unsubscribed")
    assert recipient_delivery_decision(
        purpose=MessagePurpose.TRANSACTIONAL,
        preference=PreferenceState.UNSUBSCRIBED,
        suppressions={SuppressionKind.UNSUBSCRIBE},
    ) == (True, "required_service_purpose")


def test_non_service_delivery_requires_affirmative_preference() -> None:
    assert recipient_delivery_decision(
        purpose=MessagePurpose.MARKETING,
        preference=None,
        suppressions=set(),
    ) == (False, "no_affirmative_preference")
    assert recipient_delivery_decision(
        purpose=MessagePurpose.RESEARCH_DELIVERY,
        preference=PreferenceState.SUBSCRIBED,
        suppressions=set(),
    ) == (True, "subscribed")


@pytest.mark.parametrize("source", ["inbound_email", "email_gateway", "untrusted_content", ""])
def test_inbound_or_untrusted_content_cannot_authorize_outbound(source: str) -> None:
    with pytest.raises(ValueError, match="UNTRUSTED_OUTBOUND_AUTHORIZATION_SOURCE"):
        assert_authorization_source(source)


def test_approval_requires_frozen_audience_and_recorded_approval() -> None:
    with pytest.raises(ValueError, match="FROZEN_AUDIENCE_REQUIRED"):
        validate_state_transition(
            CommunicationState.DRAFT,
            CommunicationState.AWAITING_APPROVAL,
            audience_frozen=False,
        )

    validate_state_transition(
        CommunicationState.DRAFT,
        CommunicationState.AWAITING_APPROVAL,
        audience_frozen=True,
    )

    with pytest.raises(ValueError, match="APPROVAL_RECORD_REQUIRED"):
        validate_state_transition(
            CommunicationState.AWAITING_APPROVAL,
            CommunicationState.APPROVED,
            audience_frozen=True,
        )

    validate_state_transition(
        CommunicationState.AWAITING_APPROVAL,
        CommunicationState.APPROVED,
        audience_frozen=True,
        approval_recorded=True,
    )


def test_completed_intent_cannot_be_reopened() -> None:
    with pytest.raises(ValueError, match="INVALID_COMMUNICATION_TRANSITION"):
        validate_state_transition(
            CommunicationState.COMPLETED,
            CommunicationState.DRAFT,
            audience_frozen=True,
        )


def test_audience_hash_is_order_independent_but_decision_sensitive() -> None:
    allowed = AudienceMember(1, "a@example.com", True, "subscribed")
    suppressed = AudienceMember(2, "b@example.com", False, "hard_bounce")
    first = audience_snapshot_sha256([allowed, suppressed])
    second = audience_snapshot_sha256([suppressed, allowed])
    changed = audience_snapshot_sha256(
        [allowed, AudienceMember(2, "b@example.com", True, "subscribed")]
    )

    assert first == second
    assert first != changed
