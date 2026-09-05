import pytest

from app.scientific_adapter_lab.vision_contract import (
    IdentificationStatus,
    ImageGateway,
    ImageIdentificationCandidate,
    ImageRecord,
    ImageType,
    LicenseState,
    build_unavailable_image_matrix,
)


class Repo:
    def __init__(self, records):
        self.records = records

    def records_for_taxon(self, taxon_name):
        return [record for record in self.records if record.taxon_name == taxon_name]


def image(**overrides):
    values = {
        "image_id": "img-1",
        "taxon_name": "Cattleya labiata",
        "image_type": ImageType.FIELD,
        "license_state": LicenseState.CC_BY,
        "attribution": "Example Photographer",
        "source_authority": "reviewed-source",
        "evidence_state": "reviewed",
        "broken": False,
        "curator_reviewed_binding": True,
    }
    values.update(overrides)
    return ImageRecord(**values)


def test_gateway_absence_is_unknown_without_fabricated_counts():
    matrix = ImageGateway().read_taxon("Cattleya labiata")
    assert matrix.state == "unknown"
    assert matrix.records == ()


def test_unavailable_builder_is_unknown():
    assert build_unavailable_image_matrix("Cattleya labiata").state == "unknown"


def test_automatic_identification_publication_is_prohibited():
    with pytest.raises(ValueError):
        ImageIdentificationCandidate(
            candidate_taxon="Cattleya labiata",
            confidence=0.9,
            model_identifier="offline-fixture",
            status=IdentificationStatus.CANDIDATE,
            automatic_publication=True,
        )


def test_restricted_license_is_preserved_in_serialization():
    payload = image(license_state=LicenseState.RESTRICTED).to_public_dict()
    assert payload["license_state"] == LicenseState.RESTRICTED.value


def test_broken_image_state_is_preserved():
    assert image(broken=True).to_public_dict()["broken"] is True


def test_curator_reviewed_binding_has_precedence():
    automated = image(image_id="auto", curator_reviewed_binding=False, evidence_state="candidate")
    reviewed = image(image_id="reviewed", curator_reviewed_binding=True)
    matrix = ImageGateway(Repo([automated, reviewed])).read_taxon("Cattleya labiata")
    assert matrix.records[0].image_id == "reviewed"


def test_public_serialization_contains_no_locality_coordinates():
    payload = image().to_public_dict()
    forbidden = {"latitude", "longitude", "coordinates", "gps", "collection_locality"}
    assert forbidden.isdisjoint(payload)
