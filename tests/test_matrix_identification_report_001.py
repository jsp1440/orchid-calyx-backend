from pathlib import Path

import pytest

from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import RegistryCharacter, create_registry_version
from runtime.matrix_identification_report import finalize_report, get_report, list_reports
from runtime.matrix_identification_session import _write, add_observation, create_session, get_session


def _setup(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    create_registry_version(
        registry_id="report-demo",
        version="1",
        title="Report test matrix",
        scope={"genus": "Angraecum"},
        characters=[
            RegistryCharacter("flower_color", "Flower color", weight=1),
            RegistryCharacter("spur_length_mm", "Spur length", value_type="numeric_range", weight=3),
        ],
        candidates=[
            Candidate("t1", "Taxon alpha", {"flower_color": "white", "spur_length_mm": {"min": 250, "max": 350}}),
            Candidate("t2", "Taxon beta", {"flower_color": "white", "spur_length_mm": {"min": 80, "max": 150}}),
        ],
        provenance={"source": "test"},
        actor="pytest",
        root=registry_root,
    )
    session = create_session(
        registry_id="report-demo",
        version="1",
        actor="owner-a",
        root=session_root,
        registry_root=registry_root,
    )
    add_observation(
        session["session_id"],
        character="flower_color",
        value="white",
        actor="owner-a",
        access_actor="owner-a",
        source={"kind": "user_observation", "interface": "test"},
        root=session_root,
        registry_root=registry_root,
    )
    return session["session_id"], session_root, registry_root


def test_report_is_content_addressed_and_idempotent_for_same_revision(tmp_path: Path):
    session_id, session_root, registry_root = _setup(tmp_path)
    first = finalize_report(session_id, access_actor="owner-a", root=session_root, registry_root=registry_root)
    second = finalize_report(session_id, access_actor="owner-a", root=session_root, registry_root=registry_root)
    assert first["created"] is True
    assert second["created"] is False
    assert first["report"]["report_id"] == second["report"]["report_id"]
    assert first["report"]["content_digest_sha256"] == first["report"]["report_id"]
    core = first["report"]["core"]
    assert core["session_revision"] == 1
    assert core["registry"]["checksum_sha256"]
    assert core["evaluator_version"] == "matrix-identification-evaluator/v1"
    assert core["governance"]["verified_taxonomic_identification"] is False
    assert core["governance"]["automatic_publication"] is False


def test_new_revision_creates_new_report_without_rewriting_prior_report(tmp_path: Path):
    session_id, session_root, registry_root = _setup(tmp_path)
    first = finalize_report(session_id, access_actor="owner-a", root=session_root, registry_root=registry_root)["report"]
    add_observation(
        session_id,
        character="spur_length_mm",
        value=300,
        actor="owner-a",
        access_actor="owner-a",
        root=session_root,
        registry_root=registry_root,
    )
    second = finalize_report(session_id, access_actor="owner-a", root=session_root, registry_root=registry_root)["report"]
    assert second["report_id"] != first["report_id"]
    assert second["core"]["session_revision"] == 2
    reports = list_reports(session_id, access_actor="owner-a", root=session_root)["reports"]
    assert [item["session_revision"] for item in reports] == [1, 2]
    assert get_report(session_id, first["report_id"], access_actor="owner-a", root=session_root)["core"]["session_revision"] == 1


def test_report_preserves_score_coverage_and_vision_review_boundary(tmp_path: Path):
    session_id, session_root, registry_root = _setup(tmp_path)
    session = get_session(session_id, root=session_root, access_actor="owner-a")
    session["vision_suggestions"] = [
        {
            "suggestion_id": "vision-s1",
            "analysis_id": "analysis-1",
            "vision_observation_id": "obs-v1",
            "image_id": "image-1",
            "character": "spur_length_mm",
            "state": "pending_review",
            "proposed_value": 300.0,
            "accepted_value": None,
            "machine_confidence": 0.92,
            "measurement_basis": "CALIBRATED_SCALE",
            "vision_review_state": "MACHINE_GENERATED",
            "matrix_observation_id": None,
            "review": None,
            "limitations": [],
        }
    ]
    _write(session, root=session_root)
    report = finalize_report(session_id, access_actor="owner-a", root=session_root, registry_root=registry_root)["report"]
    core = report["core"]
    candidate = core["ranking"]["candidates"][0]
    assert "score" in candidate and "coverage" in candidate
    assert len(core["observations"]) == 1
    assert core["observations"][0]["character"] == "flower_color"
    assert core["vision_review_audit"][0]["suggestion_id"] == "vision-s1"
    assert core["vision_review_audit"][0]["state"] == "pending_review"
    assert core["vision_review_audit"][0]["matrix_observation_id"] is None
    assert core["ranking"]["disclaimer"].startswith("Scores are candidate-ranking evidence")


def test_cross_owner_cannot_finalize_list_or_fetch_report(tmp_path: Path):
    session_id, session_root, registry_root = _setup(tmp_path)
    report = finalize_report(session_id, access_actor="owner-a", root=session_root, registry_root=registry_root)["report"]
    with pytest.raises(FileNotFoundError, match="identification session not found"):
        finalize_report(session_id, access_actor="owner-b", root=session_root, registry_root=registry_root)
    with pytest.raises(FileNotFoundError, match="identification session not found"):
        list_reports(session_id, access_actor="owner-b", root=session_root)
    with pytest.raises(FileNotFoundError, match="identification session not found"):
        get_report(session_id, report["report_id"], access_actor="owner-b", root=session_root)
