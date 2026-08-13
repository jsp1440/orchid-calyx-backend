from pathlib import Path
from uuid import uuid4

import pytest

from app.vision_lexicon.contracts import (
    AnalysisStatus,
    CalibrationState,
    CharacterObservation,
    ImageQualityState,
    MeasurementBasis,
    VisionAnalysisRecord,
    VisionReviewState,
)
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import create_session, get_session
from runtime.matrix_identification_vision import (
    attach_vision_analysis,
    review_vision_suggestion,
)


class FakeVisionService:
    def __init__(self, analysis, observations):
        self.analysis = analysis
        self.observations = observations

    def get_analysis(self, analysis_id):
        return self.analysis if analysis_id == self.analysis.analysis_id else None

    def list_observations_for_analysis(self, analysis_id):
        return self.observations if analysis_id == self.analysis.analysis_id else []


def _registry(root: Path) -> None:
    create_registry_version(
        registry_id="vision-bridge-demo",
        version="1",
        title="Vision bridge test matrix",
        scope={"genus": "Angraecum"},
        characters=[RegistryCharacter("spur_length_mm", "Spur length", value_type="numeric_range", weight=3)],
        candidates=[
            Candidate("t1", "Taxon alpha", {"spur_length_mm": {"min": 250, "max": 350}}),
            Candidate("t2", "Taxon beta", {"spur_length_mm": {"min": 80, "max": 150}}),
        ],
        provenance={"source": "test"},
        actor="pytest",
        root=root,
    )


def _vision(unit="mm", value=300.0):
    analysis_id = uuid4()
    analysis = VisionAnalysisRecord(
        analysis_id=analysis_id,
        image_id="image:1",
        content_hash="a" * 64,
        reference_set_id=None,
        vision_model="test-model",
        vision_model_version="1",
        analysis_version=1,
        taxon_context="Angraecum",
        taxon_confidence=None,
        calibration_state=CalibrationState.SCALE_BAR_PRESENT,
        image_quality=ImageQualityState.ACCEPTABLE,
        analysis_status=AnalysisStatus.COMPLETE,
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance={"source": "test"},
        warnings=(),
        limitations=(),
    )
    observation = CharacterObservation(
        observation_id=uuid4(),
        analysis_id=analysis_id,
        region_id=None,
        concept_id=None,
        character_id="spur_length_mm",
        character_state_id=None,
        numeric_value=value,
        unit=unit,
        relative_value=None,
        measurement_basis=MeasurementBasis.CALIBRATED_SCALE,
        confidence=0.91,
        method="test",
        evidence_region="flower spur",
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance={"model": "test-model"},
        limitations=(),
    )
    return FakeVisionService(analysis, [observation])


def _session(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)
    session = create_session(
        registry_id="vision-bridge-demo",
        version="1",
        actor="owner",
        root=session_root,
        registry_root=registry_root,
    )
    return session, session_root, registry_root


def test_machine_suggestion_does_not_enter_matrix_before_review(tmp_path: Path):
    session, session_root, registry_root = _session(tmp_path)
    service = _vision()
    result = attach_vision_analysis(
        session["session_id"],
        str(service.analysis.analysis_id),
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
        vision_service=service,
    )
    suggestion = result["suggestions"][0]
    assert suggestion["state"] == "pending_review"
    assert suggestion["proposed_value"] == 300.0
    assert suggestion["vision_review_state"] == "MACHINE_GENERATED"
    assert get_session(session["session_id"], root=session_root)["observations"] == []


def test_accepting_suggestion_uses_bound_registry_and_preserves_provenance(tmp_path: Path):
    session, session_root, registry_root = _session(tmp_path)
    service = _vision()
    attached = attach_vision_analysis(
        session["session_id"],
        str(service.analysis.analysis_id),
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
        vision_service=service,
    )
    reviewed = review_vision_suggestion(
        session["session_id"],
        attached["suggestions"][0]["suggestion_id"],
        decision="accept",
        reviewer="owner",
        certainty="probable",
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
    )
    assert reviewed["observation_added"] is True
    observation = reviewed["session"]["observations"][-1]
    assert observation["character"] == "spur_length_mm"
    assert observation["value"] == 300.0
    assert observation["recorded_by"] == "owner"
    assert observation["source"]["kind"] == "vision_reviewed_observation"
    assert observation["source"]["machine_confidence"] == 0.91


def test_ambiguous_unit_cannot_be_auto_accepted_but_can_be_revised(tmp_path: Path):
    session, session_root, registry_root = _session(tmp_path)
    service = _vision(unit="cm", value=30.0)
    attached = attach_vision_analysis(
        session["session_id"],
        str(service.analysis.analysis_id),
        access_actor="owner",
        root=session_root,
        registry_root=registry_root,
        vision_service=service,
    )
    suggestion = attached["suggestions"][0]
    assert suggestion["state"] == "needs_mapping"
    with pytest.raises(ValueError, match="unambiguous Matrix mapping"):
        review_vision_suggestion(
            session["session_id"], suggestion["suggestion_id"], decision="accept",
            reviewer="owner", certainty="certain", access_actor="owner",
            root=session_root, registry_root=registry_root,
        )
    revised = review_vision_suggestion(
        session["session_id"], suggestion["suggestion_id"], decision="revise",
        reviewer="owner", certainty="certain", revised_value=300.0,
        access_actor="owner", root=session_root, registry_root=registry_root,
    )
    assert revised["suggestion"]["state"] == "revised"
    assert revised["session"]["observations"][-1]["value"] == 300.0


def test_cross_owner_cannot_attach_or_review_vision_evidence(tmp_path: Path):
    session, session_root, registry_root = _session(tmp_path)
    service = _vision()
    with pytest.raises(FileNotFoundError):
        attach_vision_analysis(
            session["session_id"], str(service.analysis.analysis_id), access_actor="other-owner",
            root=session_root, registry_root=registry_root, vision_service=service,
        )
