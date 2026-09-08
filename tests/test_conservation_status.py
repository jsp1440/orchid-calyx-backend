import json
from datetime import date

import pytest

from app.scientific_adapter_lab.conservation_status import (
    ConservationAuthority,
    ConservationEvidenceState,
    ConservationMatrix,
    ConservationRecord,
    ConservationReviewState,
    ConservationStatusPrecedence,
    LocalityDisclosureState,
    LocalityProtectionGateway,
    build_unavailable_conservation_matrix,
)


def _record(
    *,
    authority: ConservationAuthority = ConservationAuthority.IUCN,
    review_state: ConservationReviewState = ConservationReviewState.REVIEWED,
    assessment_date: date = date(2025, 1, 2),
) -> ConservationRecord:
    return ConservationRecord(
        canonical_taxon_id="taxon-1",
        authority=authority,
        status_code="EN",
        assessment_date=assessment_date,
        source_version="2025.1",
        evidence_state=ConservationEvidenceState.PRESENT,
        review_state=review_state,
    )


@pytest.mark.parametrize(
    ("is_protected", "is_private"),
    [(True, False), (False, True), (True, True)],
)
def test_protected_or_private_locality_is_withheld(
    is_protected: bool,
    is_private: bool,
) -> None:
    result = LocalityProtectionGateway.classify(
        source_available=True,
        is_protected=is_protected,
        is_private=is_private,
    )

    assert result is LocalityDisclosureState.WITHHELD


def test_unavailable_locality_source_is_not_reported_as_generalized() -> None:
    result = LocalityProtectionGateway.classify(
        source_available=False,
        is_protected=False,
        is_private=False,
    )

    assert result is LocalityDisclosureState.UNAVAILABLE


def test_unavailable_matrix_contains_explicit_unknowns_only() -> None:
    matrix = build_unavailable_conservation_matrix("taxon-1")

    assert {record.authority for record in matrix.records} == set(
        ConservationAuthority
    )
    assert all(
        record.evidence_state is ConservationEvidenceState.UNKNOWN
        for record in matrix.records
    )
    assert all(record.status_code is None for record in matrix.records)
    assert matrix.locality_state is LocalityDisclosureState.UNAVAILABLE


def test_unknown_evidence_cannot_carry_or_fabricate_status() -> None:
    with pytest.raises(ValueError, match="cannot carry assessment claims"):
        ConservationRecord(
            canonical_taxon_id="taxon-1",
            authority=ConservationAuthority.IUCN,
            status_code="LC",
            assessment_date=None,
            source_version=None,
            evidence_state=ConservationEvidenceState.UNKNOWN,
            review_state=ConservationReviewState.UNREVIEWED,
        )

    unknown = build_unavailable_conservation_matrix("taxon-1").records[0]
    assert ConservationStatusPrecedence.select([unknown]) is None


def test_reviewed_record_outranks_provisional_authority_import() -> None:
    reviewed_regional = _record(
        authority=ConservationAuthority.REGIONAL,
        review_state=ConservationReviewState.REVIEWED,
    )
    provisional_iucn = _record(
        authority=ConservationAuthority.IUCN,
        review_state=ConservationReviewState.PROVISIONAL,
    )

    assert (
        ConservationStatusPrecedence.select(
            [provisional_iucn, reviewed_regional]
        )
        is reviewed_regional
    )


def test_precedence_is_deterministic_for_equal_review_state() -> None:
    national = _record(authority=ConservationAuthority.NATIONAL)
    iucn = _record(authority=ConservationAuthority.IUCN)

    assert ConservationStatusPrecedence.select([national, iucn]) is iucn
    assert ConservationStatusPrecedence.select([iucn, national]) is iucn


def test_public_serialization_excludes_restricted_locality_fields() -> None:
    matrix = ConservationMatrix(
        canonical_taxon_id="taxon-1",
        records=(_record(),),
        locality_state=LocalityDisclosureState.WITHHELD,
    )

    public = matrix.to_dict()
    serialized = json.dumps(public, sort_keys=True).casefold()

    for forbidden in (
        "latitude",
        "longitude",
        "coordinate",
        "collection_identifier",
        "private_locality",
    ):
        assert forbidden not in serialized
    assert public["locality_state"] == "withheld"
    assert public["taxonomy_activation_authorized"] is False
    assert public["publication_authorized"] is False
    assert json.loads(json.dumps(public, sort_keys=True)) == public


def test_matrix_rejects_mismatched_taxon_binding() -> None:
    other = ConservationRecord(
        canonical_taxon_id="taxon-2",
        authority=ConservationAuthority.IUCN,
        status_code="VU",
        assessment_date=date(2024, 3, 4),
        source_version="2024.1",
        evidence_state=ConservationEvidenceState.PRESENT,
        review_state=ConservationReviewState.REVIEWED,
    )

    with pytest.raises(ValueError, match="bind to the matrix taxon"):
        ConservationMatrix(
            canonical_taxon_id="taxon-1",
            records=(other,),
            locality_state=LocalityDisclosureState.WITHHELD,
        )
