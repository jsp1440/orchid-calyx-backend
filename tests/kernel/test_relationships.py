from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.kernel import (
    Confidence,
    OCIDFactory,
    OCIDKind,
    Relationship,
    RelationshipDirection,
    RelationshipStatus,
    RelationshipType,
    ScientificObjectValidationError,
)


def test_relationship_defaults_to_relationship_ocid() -> None:
    relationship = Relationship(
        source_ocid=OCIDFactory.new(),
        target_ocid=OCIDFactory.new(),
    )

    assert relationship.ocid.kind is OCIDKind.RELATIONSHIP
    assert relationship.relationship_type is RelationshipType.RELATED_TO
    assert relationship.direction is RelationshipDirection.DIRECTED
    assert relationship.status is RelationshipStatus.DRAFT


def test_relationship_is_immutable() -> None:
    relationship = Relationship(
        source_ocid=OCIDFactory.new(),
        target_ocid=OCIDFactory.new(),
    )

    with pytest.raises(FrozenInstanceError):
        relationship.status = RelationshipStatus.ACCEPTED  # type: ignore[misc]


def test_relationship_rejects_self_reference() -> None:
    object_ocid = OCIDFactory.new()

    with pytest.raises(ScientificObjectValidationError, match="must differ"):
        Relationship(source_ocid=object_ocid, target_ocid=object_ocid)


def test_relationship_requires_evidence_for_accepted_status() -> None:
    with pytest.raises(ScientificObjectValidationError, match="require at least one evidence"):
        Relationship(
            source_ocid=OCIDFactory.new(),
            target_ocid=OCIDFactory.new(),
            status=RelationshipStatus.ACCEPTED,
        )


def test_relationship_accepts_evidence_backed_accepted_status() -> None:
    evidence_ocid = OCIDFactory.new(OCIDKind.EVIDENCE)
    relationship = Relationship(
        source_ocid=OCIDFactory.new(),
        target_ocid=OCIDFactory.new(),
        status=RelationshipStatus.ACCEPTED,
        evidence_ocids=(evidence_ocid,),
        confidence=Confidence(0.9, method="expert_review"),
    )

    assert relationship.is_evidence_backed
    assert relationship.confidence.score == 0.9


def test_relationship_rejects_non_evidence_references() -> None:
    with pytest.raises(ScientificObjectValidationError, match="only EVIDENCE"):
        Relationship(
            source_ocid=OCIDFactory.new(),
            target_ocid=OCIDFactory.new(),
            evidence_ocids=(OCIDFactory.new(OCIDKind.ASSERTION),),
        )


def test_relationship_normalizes_temporal_validity_to_utc() -> None:
    local_tz = timezone(timedelta(hours=-7))
    valid_from = datetime(2026, 7, 23, 8, tzinfo=local_tz)
    valid_until = datetime(2026, 7, 24, 8, tzinfo=local_tz)
    relationship = Relationship(
        source_ocid=OCIDFactory.new(),
        target_ocid=OCIDFactory.new(),
        valid_from=valid_from,
        valid_until=valid_until,
    )

    assert relationship.valid_from == datetime(2026, 7, 23, 15, tzinfo=timezone.utc)
    assert relationship.valid_until == datetime(2026, 7, 24, 15, tzinfo=timezone.utc)


def test_relationship_direction_controls_traversal() -> None:
    source = OCIDFactory.new()
    target = OCIDFactory.new()
    directed = Relationship(source_ocid=source, target_ocid=target)
    bidirectional = Relationship(
        source_ocid=source,
        target_ocid=target,
        direction=RelationshipDirection.BIDIRECTIONAL,
    )

    assert directed.traversable_from(source)
    assert not directed.traversable_from(target)
    assert bidirectional.traversable_from(source)
    assert bidirectional.traversable_from(target)
