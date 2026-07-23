from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.kernel import (
    InvalidOCIDError,
    OCID,
    OCIDFactory,
    OCIDKind,
    ScientificObject,
    ScientificObjectValidationError,
)


def test_ocid_round_trip() -> None:
    ocid = OCIDFactory.new(OCIDKind.EVIDENCE)

    assert OCID.parse(str(ocid)) == ocid
    assert str(ocid).startswith("OC:EVIDENCE:")


def test_ocid_rejects_invalid_values() -> None:
    with pytest.raises(InvalidOCIDError):
        OCID.parse("not-an-ocid")


def test_scientific_object_is_immutable_and_uses_utc() -> None:
    obj = ScientificObject(metadata={"source": "test"})

    assert obj.created_at.tzinfo == timezone.utc
    assert obj.metadata["source"] == "test"
    with pytest.raises((FrozenInstanceError, AttributeError)):
        obj.object_type = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        obj.metadata["source"] = "changed"  # type: ignore[index]


def test_scientific_object_normalizes_timestamp_to_utc() -> None:
    obj = ScientificObject(created_at=datetime.now().astimezone())

    assert obj.created_at.tzinfo == timezone.utc


def test_scientific_object_rejects_naive_timestamp() -> None:
    with pytest.raises(ScientificObjectValidationError):
        ScientificObject(created_at=datetime.now())


def test_specialized_object_requires_specialized_ocid_kind() -> None:
    with pytest.raises(ScientificObjectValidationError):
        ScientificObject(object_type="evidence")
