from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.kernel import Evidence, EvidenceType, OCIDKind, Provenance, ScientificObjectValidationError


def test_evidence_defaults_to_evidence_ocid_and_fingerprint() -> None:
    evidence = Evidence(
        title="A documented orchid observation",
        evidence_type=EvidenceType.OBSERVATION,
        provenance=Provenance(source_name="iNaturalist", source_record_id="123"),
        content={"taxon": "Orchidaceae", "count": 1},
    )

    assert evidence.ocid.kind is OCIDKind.EVIDENCE
    assert len(evidence.fingerprint) == 64


def test_equivalent_evidence_has_same_fingerprint() -> None:
    provenance = Provenance(source_name="GBIF", source_record_id="abc")
    first = Evidence(
        title="Occurrence record",
        evidence_type=EvidenceType.DATASET,
        provenance=provenance,
        content={"lat": 1, "lon": 2},
    )
    second = Evidence(
        title="Occurrence record",
        evidence_type=EvidenceType.DATASET,
        provenance=provenance,
        content={"lon": 2, "lat": 1},
    )

    assert first.fingerprint == second.fingerprint


def test_content_and_provenance_metadata_are_read_only() -> None:
    provenance = Provenance(source_name="BHL", source_record_id="42", metadata={"page": 7})
    evidence = Evidence(title="Plate", provenance=provenance, content={"caption": "Orchid plate"})

    with pytest.raises(TypeError):
        evidence.content["caption"] = "changed"
    with pytest.raises(TypeError):
        provenance.metadata["page"] = 8


def test_evidence_is_frozen() -> None:
    evidence = Evidence(title="Specimen", provenance=Provenance("Herbarium", "sheet-1"))

    with pytest.raises(FrozenInstanceError):
        evidence.title = "changed"


def test_provenance_normalizes_timestamp_to_utc() -> None:
    provenance = Provenance(
        source_name="Source",
        source_record_id="1",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert provenance.retrieved_at.tzinfo is timezone.utc


def test_blank_provenance_source_is_rejected() -> None:
    with pytest.raises(ScientificObjectValidationError):
        Provenance(source_name=" ", source_record_id="1")


def test_blank_evidence_title_is_rejected() -> None:
    with pytest.raises(ScientificObjectValidationError):
        Evidence(title=" ", provenance=Provenance("Source", "1"))
