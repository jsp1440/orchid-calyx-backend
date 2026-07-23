"""Tests for KERNEL-003 scientific assertion contracts."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.kernel.assertions import (
    Assertion,
    AssertionObject,
    AssertionStatus,
    Confidence,
)
from app.kernel.exceptions import ScientificObjectValidationError
from app.kernel.identity import OCIDFactory, OCIDKind


def _evidence_ocid():
    return OCIDFactory.new(OCIDKind.EVIDENCE)


def test_assertion_is_immutable_and_evidence_backed() -> None:
    evidence_ocid = _evidence_ocid()
    assertion = Assertion(
        subject_ocid=OCIDFactory.new(OCIDKind.KNOWLEDGE_OBJECT),
        predicate="has_pollinator",
        assertion_object=AssertionObject(value="Euglossa dilemma", datatype="taxon_name"),
        evidence_ocids=(evidence_ocid,),
        confidence=Confidence(0.87, method="independent_sources"),
        status=AssertionStatus.ACCEPTED,
        qualifiers={"region": "Florida"},
    )

    assert assertion.ocid.kind is OCIDKind.ASSERTION
    assert assertion.is_evidence_backed
    assert assertion.qualifiers["region"] == "Florida"
    with pytest.raises(FrozenInstanceError):
        assertion.predicate = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        assertion.qualifiers["region"] = "changed"  # type: ignore[index]


def test_confidence_must_be_normalized() -> None:
    with pytest.raises(ScientificObjectValidationError):
        Confidence(1.01)
    with pytest.raises(ScientificObjectValidationError):
        Confidence(-0.01)


def test_assertion_object_requires_exactly_one_representation() -> None:
    with pytest.raises(ScientificObjectValidationError):
        AssertionObject()
    with pytest.raises(ScientificObjectValidationError):
        AssertionObject(ocid=OCIDFactory.new(), value="duplicate")


def test_assertion_evidence_references_must_be_evidence_ocids() -> None:
    with pytest.raises(ScientificObjectValidationError):
        Assertion(
            predicate="has_trait",
            assertion_object=AssertionObject(value="fragrant"),
            evidence_ocids=(OCIDFactory.new(OCIDKind.ASSERTION),),
        )


def test_accepted_assertion_requires_evidence() -> None:
    with pytest.raises(ScientificObjectValidationError):
        Assertion(
            predicate="occurs_in",
            assertion_object=AssertionObject(value="Ecuador"),
            status=AssertionStatus.ACCEPTED,
        )


def test_draft_assertion_may_exist_before_evidence_is_attached() -> None:
    assertion = Assertion(
        predicate="candidate_trait",
        assertion_object=AssertionObject(value="pendent"),
    )

    assert assertion.status is AssertionStatus.DRAFT
    assert not assertion.is_evidence_backed


def test_assertion_temporal_validity_is_normalized_and_ordered() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-8)))
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assertion = Assertion(
        predicate="accepted_name",
        assertion_object=AssertionObject(value="Cattleya maxima"),
        valid_from=start,
        valid_until=end,
    )

    assert assertion.valid_from is not None
    assert assertion.valid_from.tzinfo is timezone.utc
    with pytest.raises(ScientificObjectValidationError):
        Assertion(
            predicate="accepted_name",
            assertion_object=AssertionObject(value="Cattleya maxima"),
            valid_from=end,
            valid_until=start,
        )


def test_duplicate_evidence_references_are_rejected() -> None:
    evidence_ocid = _evidence_ocid()
    with pytest.raises(ScientificObjectValidationError):
        Assertion(
            predicate="has_image",
            assertion_object=AssertionObject(value="image-1"),
            evidence_ocids=(evidence_ocid, evidence_ocid),
        )
