from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.kernel import (
    EventType,
    OCIDFactory,
    OCIDKind,
    ScientificEvent,
    ScientificObjectValidationError,
)


def test_event_defaults_to_event_ocid() -> None:
    event = ScientificEvent(subject_ocid=OCIDFactory.new())

    assert event.ocid.kind is OCIDKind.EVENT
    assert event.event_type is EventType.EVIDENCE_REGISTERED
    assert event.sequence == 1


def test_event_is_immutable() -> None:
    event = ScientificEvent(subject_ocid=OCIDFactory.new())

    with pytest.raises(FrozenInstanceError):
        event.sequence = 2  # type: ignore[misc]


def test_event_rejects_non_event_ocid() -> None:
    with pytest.raises(ScientificObjectValidationError, match="EVENT OCID"):
        ScientificEvent(
            ocid=OCIDFactory.new(OCIDKind.ASSERTION),
            subject_ocid=OCIDFactory.new(),
        )


def test_event_rejects_non_publication_scope() -> None:
    with pytest.raises(ScientificObjectValidationError, match="PUBLICATION OCID"):
        ScientificEvent(
            subject_ocid=OCIDFactory.new(),
            publication_ocid=OCIDFactory.new(OCIDKind.ASSERTION),
        )


def test_event_rejects_non_event_causation_reference() -> None:
    with pytest.raises(ScientificObjectValidationError, match="EVENT OCID"):
        ScientificEvent(
            subject_ocid=OCIDFactory.new(),
            causation_event_ocid=OCIDFactory.new(OCIDKind.EVIDENCE),
        )


def test_event_rejects_self_causation() -> None:
    event_ocid = OCIDFactory.new(OCIDKind.EVENT)

    with pytest.raises(ScientificObjectValidationError, match="cannot cause itself"):
        ScientificEvent(
            ocid=event_ocid,
            subject_ocid=OCIDFactory.new(),
            causation_event_ocid=event_ocid,
        )


def test_event_normalizes_timestamp_and_payload() -> None:
    local_tz = timezone(timedelta(hours=-7))
    occurred_at = datetime(2026, 7, 23, 12, tzinfo=local_tz)
    payload = {"status": "accepted"}
    event = ScientificEvent(
        subject_ocid=OCIDFactory.new(),
        occurred_at=occurred_at,
        actor="  curator@example.org  ",
        payload=payload,
    )
    payload["status"] = "changed"

    assert event.occurred_at == datetime(2026, 7, 23, 19, tzinfo=timezone.utc)
    assert event.actor == "curator@example.org"
    assert event.payload["status"] == "accepted"


def test_event_publication_scope_property() -> None:
    event = ScientificEvent(
        event_type=EventType.PUBLICATION_COMMITTED,
        subject_ocid=OCIDFactory.new(OCIDKind.PUBLICATION),
        publication_ocid=OCIDFactory.new(OCIDKind.PUBLICATION),
        correlation_ocid=OCIDFactory.new(),
        sequence=2,
    )

    assert event.is_publication_scoped
