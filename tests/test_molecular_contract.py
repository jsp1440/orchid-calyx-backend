import pytest

from app.scientific_adapter_lab.molecular_contract import (
    MolecularGateway,
    SequenceBindingState,
    SequenceRecord,
    build_unavailable_molecular_matrix,
)


class Repo:
    def __init__(self, records):
        self.records = records

    def records_for_taxon(self, taxon_name):
        return [record for record in self.records if record.taxon_name == taxon_name]


def record(**overrides):
    values = {
        "taxon_name": "Phalaenopsis aphrodite",
        "taxon_kind": "orchid",
        "accession_id": "AB123456",
        "locus": "ITS",
        "source_authority": "GenBank",
        "tissue_type": "leaf",
        "life_stage": "adult",
        "binding_state": SequenceBindingState.ACCESSION_VERIFIED,
        "method": "Sanger",
        "reviewed_taxon": True,
        "accession_verified": True,
        "unpublished": False,
    }
    values.update(overrides)
    return SequenceRecord(**values)


def test_unavailable_gateway_is_unknown_not_zero_or_fabricated():
    matrix = MolecularGateway().read_taxon("Phalaenopsis aphrodite")
    assert matrix.state is SequenceBindingState.UNKNOWN
    assert matrix.records == ()
    assert matrix.to_public_dict()["records"] == []


def test_unavailable_builder_is_all_unknown():
    matrix = build_unavailable_molecular_matrix("Rhizoctonia solani")
    assert matrix.state is SequenceBindingState.UNKNOWN
    assert matrix.records == ()


def test_verified_binding_requires_real_verified_accession():
    with pytest.raises(ValueError):
        record(accession_id=None)
    with pytest.raises(ValueError):
        record(accession_verified=False)


def test_conflict_is_never_collapsed_to_verified():
    conflict = record(
        binding_state=SequenceBindingState.CONFLICT,
        accession_verified=False,
        reviewed_taxon=True,
    )
    verified = record(accession_id="AB999999")
    matrix = MolecularGateway(Repo([verified, conflict])).read_taxon(
        "Phalaenopsis aphrodite"
    )
    assert matrix.state is SequenceBindingState.CONFLICT


def test_verified_reviewed_record_has_highest_precedence():
    provisional = record(
        accession_id="AB000001",
        binding_state=SequenceBindingState.TAXON_UNRESOLVED,
        accession_verified=False,
        reviewed_taxon=False,
    )
    reviewed = record(accession_id="AB000002")
    matrix = MolecularGateway(Repo([provisional, reviewed])).read_taxon(
        "Phalaenopsis aphrodite"
    )
    assert matrix.records[0].accession_id == "AB000002"


def test_unpublished_accession_is_redacted_on_serialization():
    unpublished = record(
        unpublished=True,
        binding_state=SequenceBindingState.TAXON_UNRESOLVED,
        accession_verified=False,
    )
    payload = unpublished.to_public_dict()
    assert payload["accession_id"] is None
    assert payload["binding_state"] == SequenceBindingState.UNKNOWN.value
    forbidden = {"latitude", "longitude", "coordinates", "collection_locality"}
    assert forbidden.isdisjoint(payload)
