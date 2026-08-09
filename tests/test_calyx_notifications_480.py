from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.notification_service import NotificationService


def preferences() -> dict:
    return {
        "recipient_id": "owner",
        "timezone": "UTC",
        "quiet_hours": {"start": "22:00", "end": "07:00"},
        "minimum_severity": "medium",
        "digest_enabled": True,
        "digest_group": "operations",
        "channels": ["in_app"],
    }


def event(event_id: str, *, severity: str = "high", event_type: str = "delivery_blocker") -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "severity": severity,
        "recipient_id": "owner",
        "title": "Fixture blocker",
        "message": "A governed fixture needs owner attention.",
        "source_ref": "calyx://fixture/blocker/1",
        "dedupe_key": "fixture:blocker:1",
        "digest_group": "operations",
    }


def test_preferences_are_in_app_only_and_store_no_provider_secret(tmp_path: Path):
    service = NotificationService(tmp_path)
    saved = service.save_preferences("owner-a", preferences())
    assert saved["channels"] == ["in_app"]
    assert saved["external_delivery_authorized"] is False
    assert saved["provider_secret_storage_authorized"] is False
    with pytest.raises(ValueError, match="NOTIFICATION_EXTERNAL_CHANNEL_NOT_AUTHORIZED"):
        service.save_preferences("owner-a", preferences() | {"channels": ["email"]})


def test_exact_event_replay_is_idempotent_and_conflicting_id_reuse_fails(tmp_path: Path):
    service = NotificationService(tmp_path)
    first = service.create_event("owner-a", event("evt-1"))
    replay = service.create_event("owner-a", event("evt-1"))
    assert replay["event_digest"] == first["event_digest"]
    assert replay["created_at"] == first["created_at"]
    with pytest.raises(ValueError, match="NOTIFICATION_IMMUTABLE_EVENT_CONFLICT"):
        service.create_event("owner-a", event("evt-1") | {"message": "different event content"})


def test_deduplication_collapses_repeated_actionable_event(tmp_path: Path):
    service = NotificationService(tmp_path)
    service.save_preferences("owner-a", preferences())
    first = service.create_event("owner-a", event("evt-1"))
    before_state_digest = first["state_digest"]
    second = service.create_event("owner-a", event("evt-2"))
    assert second["event_id"] == first["event_id"]
    assert second["duplicate_count"] == 1
    assert second["state_digest"] != before_state_digest
    assert second["event_digest"] == first["event_digest"]


def test_quiet_hours_defer_noncritical_but_not_critical(tmp_path: Path):
    service = NotificationService(tmp_path)
    service.save_preferences("owner-a", preferences())
    service.create_event("owner-a", event("evt-high", severity="high") | {"dedupe_key": "high"})
    service.create_event("owner-a", event("evt-critical", severity="critical") | {"dedupe_key": "critical"})
    pending = service.pending_for_recipient(
        "owner-a", "owner", at=datetime(2026, 8, 9, 23, 0, tzinfo=UTC)
    )
    assert pending["quiet_hours_active"] is True
    assert [item["event_id"] for item in pending["immediate"]] == ["evt-critical"]
    assert [item["event_id"] for item in pending["deferred"]] == ["evt-high"]


def test_digest_acknowledgement_and_escalation_are_provider_neutral(tmp_path: Path):
    service = NotificationService(tmp_path)
    service.save_preferences("owner-a", preferences())
    created = service.create_event("owner-a", event("evt-1"))
    digest = service.digest("owner-a", "owner")
    assert digest["event_count"] == 1
    assert digest["provider_send_authorized"] is False
    escalated = service.escalate("owner-a", "evt-1", actor="owner-a", rationale="still unresolved")
    assert escalated["escalation_level"] == 1
    assert escalated["state_digest"] != created["state_digest"]
    acknowledged = service.acknowledge("owner-a", "evt-1", actor="owner-a", note="reviewed")
    assert acknowledged["state"] == "acknowledged"
    assert acknowledged["event_digest"] == created["event_digest"]
    with pytest.raises(ValueError, match="NOTIFICATION_ACKNOWLEDGED_EVENT_CANNOT_ESCALATE"):
        service.escalate("owner-a", "evt-1", actor="owner-a", rationale="should fail")


def test_digest_respects_preference_and_orders_severity_descending(tmp_path: Path):
    service = NotificationService(tmp_path)
    service.save_preferences("owner-a", preferences() | {"quiet_hours": {}})
    service.create_event("owner-a", event("evt-medium", severity="medium") | {"dedupe_key": "medium"})
    service.create_event("owner-a", event("evt-critical", severity="critical") | {"dedupe_key": "critical"})
    digest = service.digest("owner-a", "owner")
    assert [item["event_id"] for item in digest["groups"]["operations"]] == ["evt-critical", "evt-medium"]
    service.save_preferences("owner-a", preferences() | {"quiet_hours": {}, "digest_enabled": False})
    disabled = service.digest("owner-a", "owner")
    assert disabled["digest_enabled"] is False
    assert disabled["event_count"] == 0
    assert disabled["groups"] == {}


def test_live_provider_receipt_is_rejected_but_fixture_receipt_is_recorded(tmp_path: Path):
    service = NotificationService(tmp_path)
    created = service.create_event("owner-a", event("evt-1"))
    with pytest.raises(ValueError, match="NOTIFICATION_LIVE_PROVIDER_NOT_AUTHORIZED"):
        service.record_delivery_receipt("owner-a", "evt-1", {"provider": "sendgrid", "status": "sent"})
    recorded = service.record_delivery_receipt(
        "owner-a", "evt-1", {"provider": "provider_neutral_fixture", "provider_message_id": "fixture-1", "status": "recorded"}
    )
    assert recorded["delivery_receipts"][0]["live_provider_send"] is False
    assert recorded["event_digest"] == created["event_digest"]
    assert recorded["state_digest"] != created["state_digest"]


def test_readiness_never_authorizes_unsolicited_external_messaging(tmp_path: Path):
    service = NotificationService(tmp_path)
    service.create_event("owner-a", event("evt-1"))
    readiness = service.readiness("owner-a")
    assert readiness["pending_count"] == 1
    assert readiness["unsolicited_external_messaging_authorized"] is False
    assert readiness["autonomous_commitment_authorized"] is False
    assert readiness["provider_secret_storage_authorized"] is False
    assert readiness["live_provider_send_authorized"] is False
    assert readiness["deployment_authorized"] is False
