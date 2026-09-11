"""Tests for OC-VISION-001 — Vision/image pipeline schema, license attribution, identification contract.

Covers:
- UNKNOWN fallback (ImageGateway unavailable, build_unavailable_image_matrix)
- Auto-publication prohibition (ImageIdentificationCandidate governance enforcement)
- License-state integrity (RESTRICTED never silently promoted to usable)
- Broken-image detection
- Source precedence (CURATOR_REVIEWED > UNVERIFIED > AUTOMATED_SUGGESTION)
- Serialization safety (no restricted locality coordinates)
"""
from __future__ import annotations

import json

import pytest

from app.scientific_adapter_lab.vision_image_pipeline import (
    SCHEMA_VERSION,
    IdentificationStatus,
    ImageEvidenceState,
    ImageGateway,
    ImageIdentificationCandidate,
    ImageRecord,
    ImageSourcePrecedence,
    ImageType,
    LicenseState,
    build_unavailable_image_matrix,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _image_record(
    image_id: str = "img-001",
    taxon_id: str = "taxon-001",
    taxon_name: str = "Cattleya labiata",
    image_type: ImageType = ImageType.HERBARIUM,
    license_state: LicenseState = LicenseState.CC_BY,
    attribution: str = "Field Museum — CC-BY-4.0",
    source_authority: str = "iDigBio",
    evidence_state: ImageEvidenceState = ImageEvidenceState.CURATOR_REVIEWED,
    is_broken: bool = False,
    is_sensitive_locality: bool = False,
) -> ImageRecord:
    return ImageRecord(
        image_id=image_id,
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        image_type=image_type,
        license_state=license_state,
        attribution=attribution,
        source_authority=source_authority,
        evidence_state=evidence_state,
        is_broken=is_broken,
        is_sensitive_locality=is_sensitive_locality,
    )


def _candidate(
    candidate_taxon_id: str = "taxon-001",
    candidate_taxon_name: str = "Cattleya labiata",
    confidence: float = 0.85,
    model_identifier: str = "vision-model-v1",
    status: IdentificationStatus = IdentificationStatus.CANDIDATE,
    automatic_publication: bool = False,
) -> ImageIdentificationCandidate:
    return ImageIdentificationCandidate(
        candidate_taxon_id=candidate_taxon_id,
        candidate_taxon_name=candidate_taxon_name,
        confidence=confidence,
        model_identifier=model_identifier,
        status=status,
        automatic_publication=automatic_publication,
    )


# ---------------------------------------------------------------------------
# Auto-publication prohibition
# ---------------------------------------------------------------------------


class TestAutopublicationProhibition:
    def test_automatic_publication_false_is_valid(self):
        c = _candidate(automatic_publication=False)
        assert c.automatic_publication is False

    def test_automatic_publication_true_raises(self):
        with pytest.raises(ValueError, match="automatic_publication"):
            _candidate(automatic_publication=True)

    def test_governance_violation_sentinel_in_message(self):
        with pytest.raises(ValueError, match="VISION_PIPELINE_GOVERNANCE_VIOLATION"):
            _candidate(automatic_publication=True)

    def test_candidate_status_default(self):
        c = _candidate()
        assert c.status == IdentificationStatus.CANDIDATE

    def test_reviewed_accepted_status_allowed(self):
        c = _candidate(status=IdentificationStatus.REVIEWED_ACCEPTED)
        assert c.status == IdentificationStatus.REVIEWED_ACCEPTED


# ---------------------------------------------------------------------------
# License-state integrity
# ---------------------------------------------------------------------------


class TestLicenseStateIntegrity:
    def test_cc_by_is_usable(self):
        rec = _image_record(license_state=LicenseState.CC_BY)
        assert rec.is_usable() is True

    def test_cc0_is_usable(self):
        rec = _image_record(license_state=LicenseState.CC0)
        assert rec.is_usable() is True

    def test_cc_by_sa_is_usable(self):
        rec = _image_record(license_state=LicenseState.CC_BY_SA)
        assert rec.is_usable() is True

    def test_cc_by_nc_is_usable(self):
        rec = _image_record(license_state=LicenseState.CC_BY_NC)
        assert rec.is_usable() is True

    def test_restricted_not_usable(self):
        rec = _image_record(license_state=LicenseState.RESTRICTED)
        assert rec.is_usable() is False

    def test_unknown_not_usable(self):
        rec = _image_record(license_state=LicenseState.UNKNOWN)
        assert rec.is_usable() is False

    def test_restricted_serializes_as_restricted(self):
        rec = _image_record(license_state=LicenseState.RESTRICTED)
        parsed = json.loads(rec.serialize_as_json())
        assert parsed["license_state"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# Broken-image detection
# ---------------------------------------------------------------------------


class TestBrokenImageDetection:
    def test_broken_image_not_usable(self):
        rec = _image_record(is_broken=True, license_state=LicenseState.CC_BY)
        assert rec.is_usable() is False

    def test_non_broken_image_usable(self):
        rec = _image_record(is_broken=False, license_state=LicenseState.CC_BY)
        assert rec.is_usable() is True

    def test_unavailable_stubs_are_broken(self):
        stubs = build_unavailable_image_matrix(["t1"])
        assert stubs[0].is_broken is True

    def test_broken_flag_serialized(self):
        rec = _image_record(is_broken=True)
        parsed = json.loads(rec.serialize_as_json())
        assert parsed["is_broken"] is True


# ---------------------------------------------------------------------------
# ImageGateway — UNKNOWN fallback
# ---------------------------------------------------------------------------


class TestImageGateway:
    def test_unavailable_count_is_none(self):
        gw = ImageGateway(available=False)
        assert gw.get_image_count("taxon-001") is None

    def test_unavailable_never_returns_zero(self):
        gw = ImageGateway(available=False)
        assert gw.get_image_count("any") != 0

    def test_available_raises_not_implemented(self):
        gw = ImageGateway(available=True)
        with pytest.raises(NotImplementedError, match="IMAGE_GATEWAY_NOT_IMPLEMENTED"):
            gw.get_image_count("taxon-001")

    def test_default_gateway_is_unavailable(self):
        gw = ImageGateway()
        assert gw.is_available() is False


# ---------------------------------------------------------------------------
# Source precedence
# ---------------------------------------------------------------------------


class TestImageSourcePrecedence:
    def test_curator_reviewed_beats_automated(self):
        curated = _image_record(evidence_state=ImageEvidenceState.CURATOR_REVIEWED, image_id="c")
        auto = _image_record(evidence_state=ImageEvidenceState.AUTOMATED_SUGGESTION, image_id="a")
        prec = ImageSourcePrecedence()
        assert prec.resolve([auto, curated]).evidence_state == ImageEvidenceState.CURATOR_REVIEWED

    def test_curator_reviewed_beats_unverified(self):
        curated = _image_record(evidence_state=ImageEvidenceState.CURATOR_REVIEWED, image_id="c")
        unverif = _image_record(evidence_state=ImageEvidenceState.UNVERIFIED, image_id="u")
        prec = ImageSourcePrecedence()
        assert prec.resolve([unverif, curated]).evidence_state == ImageEvidenceState.CURATOR_REVIEWED

    def test_unverified_beats_automated(self):
        unverif = _image_record(evidence_state=ImageEvidenceState.UNVERIFIED, image_id="u")
        auto = _image_record(evidence_state=ImageEvidenceState.AUTOMATED_SUGGESTION, image_id="a")
        prec = ImageSourcePrecedence()
        assert prec.resolve([auto, unverif]).evidence_state == ImageEvidenceState.UNVERIFIED

    def test_any_beats_unavailable(self):
        auto = _image_record(evidence_state=ImageEvidenceState.AUTOMATED_SUGGESTION, image_id="a")
        unavail = _image_record(evidence_state=ImageEvidenceState.UNAVAILABLE, image_id="u")
        prec = ImageSourcePrecedence()
        assert prec.resolve([unavail, auto]).evidence_state == ImageEvidenceState.AUTOMATED_SUGGESTION

    def test_empty_raises(self):
        prec = ImageSourcePrecedence()
        with pytest.raises(ValueError, match="IMAGE_SOURCE_EMPTY"):
            prec.resolve([])

    def test_is_curator_reviewed_true(self):
        rec = _image_record(evidence_state=ImageEvidenceState.CURATOR_REVIEWED)
        prec = ImageSourcePrecedence()
        assert prec.is_curator_reviewed(rec) is True

    def test_is_curator_reviewed_false_for_automated(self):
        rec = _image_record(evidence_state=ImageEvidenceState.AUTOMATED_SUGGESTION)
        prec = ImageSourcePrecedence()
        assert prec.is_curator_reviewed(rec) is False


# ---------------------------------------------------------------------------
# build_unavailable_image_matrix
# ---------------------------------------------------------------------------


class TestBuildUnavailableImageMatrix:
    def test_unavailable_evidence_state(self):
        stubs = build_unavailable_image_matrix(["t1", "t2"])
        assert all(r.evidence_state == ImageEvidenceState.UNAVAILABLE for r in stubs)

    def test_unknown_license_state(self):
        stubs = build_unavailable_image_matrix(["t1"])
        assert stubs[0].license_state == LicenseState.UNKNOWN

    def test_taxon_ids_preserved(self):
        stubs = build_unavailable_image_matrix(["taxon-A", "taxon-B"])
        assert [s.taxon_id for s in stubs] == ["taxon-A", "taxon-B"]

    def test_empty_input_returns_empty(self):
        assert build_unavailable_image_matrix([]) == []


# ---------------------------------------------------------------------------
# ImageRecord validation
# ---------------------------------------------------------------------------


class TestImageRecordValidation:
    def test_valid_record_passes(self):
        _image_record().validate()

    def test_empty_image_id_raises(self):
        rec = _image_record(image_id="")
        with pytest.raises(ValueError, match="image_id"):
            rec.validate()

    def test_empty_taxon_id_raises(self):
        rec = _image_record(taxon_id="")
        with pytest.raises(ValueError, match="taxon_id"):
            rec.validate()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestVisionSerialization:
    def test_schema_version_present(self):
        parsed = json.loads(_image_record().serialize_as_json())
        assert parsed["schema_version"] == SCHEMA_VERSION

    def test_candidate_serializes_correctly(self):
        c = _candidate()
        parsed = json.loads(c.serialize_as_json())
        assert parsed["status"] == "CANDIDATE"
        assert parsed["automatic_publication"] is False

    def test_unavailable_stubs_serialize(self):
        stubs = build_unavailable_image_matrix(["t1"])
        parsed = json.loads(stubs[0].serialize_as_json())
        assert parsed["evidence_state"] == "UNAVAILABLE"
        assert parsed["license_state"] == "UNKNOWN"

    def test_no_locality_coordinates_in_output(self):
        parsed = json.loads(_image_record().serialize_as_json())
        forbidden = {"lat", "lon", "latitude", "longitude", "locality", "collector"}
        assert not forbidden & set(parsed.keys())

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            _candidate(confidence=1.1)
