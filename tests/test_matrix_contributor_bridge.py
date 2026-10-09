"""Focused tests for the review-gated contributor → Matrix bridge (AC-2)."""

from pathlib import Path

import pytest

from runtime.contributor_image_intake import intake_contributor_batch
from runtime.matrix_contributor_bridge import (
    attach_contributor_extractions,
    build_contributor_evidence_record,
    compare_with_governed_sources,
    review_contributor_suggestion,
)
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import (
    create_session,
    evaluate_session,
    get_session,
)


def _registry(root: Path) -> None:
    create_registry_version(
        registry_id="phragmipedium-demo",
        version="1",
        title="Phragmipedium bounded diagnostic matrix",
        scope={"genus": "Phragmipedium"},
        characters=[
            RegistryCharacter("petal_color", "Petal color", weight=1),
            RegistryCharacter("pouch_shape", "Pouch shape", weight=2),
            RegistryCharacter("leaf_length_cm", "Leaf length", value_type="numeric_range", weight=1),
        ],
        candidates=[
            Candidate(
                "world-plants:phragmipedium-besseae",
                "Phragmipedium besseae",
                {
                    "petal_color": "red",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 20, "max": 35},
                },
            ),
            Candidate(
                "world-plants:phragmipedium-kovachii",
                "Phragmipedium kovachii",
                {
                    "petal_color": "pink",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 30, "max": 60},
                },
            ),
        ],
        provenance={"source": "test governed assertions"},
        actor="test",
        root=root,
    )


def _staged_image():
    result = intake_contributor_batch(
        [
            {
                "submission_id": "sub-100",
                "contributor_id": "member-7",
                "contributor_display_name": "R. Orchidist",
                "permission_grant": "cc-by-nc",
                "rights_holder_affirmed": True,
                "original_object_ref": "objects/originals/sub-100.jpg",
                "content_sha256": "c" * 64,
                "mime_type": "image/jpeg",
                "taxon_name": None,
                "taxon_certainty": "unknown",
                "candidate_taxa": [{"name": "Phragmipedium kovachii"}],
                "provenance": {"channel": "member-upload"},
            }
        ],
        batch_id="batch-100",
    )
    assert len(result.staged) == 1
    return result.staged[0]


def _session(tmp_path: Path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    _registry(registry_root)
    staged = _staged_image()
    session = create_session(
        registry_id="phragmipedium-demo",
        version="1",
        actor="member-7",
        metadata={"contributor_submission_id": staged.submission_id},
        root=session_root,
        registry_root=registry_root,
    )
    return staged, session, session_root, registry_root


def _extractions():
    return [
        {
            "character": "petal_color",
            "value": "pink",
            "machine_confidence": 0.81,
            "extractor": "stub-vision",
            "extractor_version": "0.0.1",
            "extraction_method": "test_stub",
        },
        {
            "character": "pouch_shape",
            "value": "slipper",
            "machine_confidence": 0.62,
            "extractor": "stub-vision",
            "extractor_version": "0.0.1",
            "extraction_method": "test_stub",
        },
        {
            "character": "unregistered_character",
            "value": "??",
            "machine_confidence": 0.5,
            "extractor": "stub-vision",
            "extractor_version": "0.0.1",
            "extraction_method": "test_stub",
        },
    ]


def test_machine_extractions_never_score_before_review(tmp_path: Path):
    staged, session, session_root, registry_root = _session(tmp_path)
    attached = attach_contributor_extractions(
        session["session_id"],
        staged,
        _extractions(),
        access_actor="member-7",
        root=session_root,
        registry_root=registry_root,
    )
    assert attached["added"] == 3
    stored = get_session(session["session_id"], root=session_root, access_actor="member-7")
    assert stored["observations"] == []
    states = {item["character"]: item["state"] for item in stored["contributor_suggestions"]}
    assert states["petal_color"] == "pending_review"
    assert states["pouch_shape"] == "pending_review"
    assert states["unregistered_character"] == "needs_mapping"

    evaluation = evaluate_session(
        session["session_id"], access_actor="member-7",
        root=session_root, registry_root=registry_root,
    )
    assert evaluation["report"]["observation_count"] == 0


def test_accept_requires_reviewer_identity_and_explicit_certainty(tmp_path: Path):
    staged, session, session_root, registry_root = _session(tmp_path)
    attach_contributor_extractions(
        session["session_id"], staged, _extractions(),
        access_actor="member-7", root=session_root, registry_root=registry_root,
    )
    suggestion_id = next(
        item["suggestion_id"]
        for item in get_session(session["session_id"], root=session_root)["contributor_suggestions"]
        if item["character"] == "petal_color"
    )
    with pytest.raises(ValueError, match="reviewer identity is required"):
        review_contributor_suggestion(
            session["session_id"], suggestion_id, decision="accept", reviewer=" ",
            certainty="certain", access_actor="member-7",
            root=session_root, registry_root=registry_root,
        )
    with pytest.raises(ValueError, match="certainty is required"):
        review_contributor_suggestion(
            session["session_id"], suggestion_id, decision="accept", reviewer="expert-1",
            certainty=None, access_actor="member-7",
            root=session_root, registry_root=registry_root,
        )


def test_accepted_suggestion_scores_with_full_provenance(tmp_path: Path):
    staged, session, session_root, registry_root = _session(tmp_path)
    attach_contributor_extractions(
        session["session_id"], staged, _extractions(),
        access_actor="member-7", root=session_root, registry_root=registry_root,
    )
    suggestions = get_session(session["session_id"], root=session_root)["contributor_suggestions"]
    petal = next(item for item in suggestions if item["character"] == "petal_color")
    result = review_contributor_suggestion(
        session["session_id"], petal["suggestion_id"],
        decision="accept", reviewer="expert-1", certainty="probable",
        access_actor="member-7", root=session_root, registry_root=registry_root,
    )
    assert result["observation_added"] is True
    stored = get_session(session["session_id"], root=session_root, access_actor="member-7")
    assert len(stored["observations"]) == 1
    observation = stored["observations"][0]
    assert observation["source"]["kind"] == "contributor_image_reviewed"
    assert observation["source"]["reviewer"] == "expert-1"
    assert observation["source"]["content_sha256"] == "c" * 64
    assert observation["source"]["contributor_id"] == "member-7"
    assert observation["source"]["permission_grant"] == "cc-by-nc"
    assert observation["source"]["machine_confidence"] == 0.81
    assert observation["certainty"] == "probable"  # reviewer certainty, not machine confidence
    assert observation["recorded_by"] == "expert-1"

    evaluation = evaluate_session(
        session["session_id"], access_actor="member-7",
        root=session_root, registry_root=registry_root,
    )
    assert evaluation["report"]["candidates"][0]["scientific_name"] == "Phragmipedium kovachii"


def test_rejected_suggestion_is_audit_only_and_final(tmp_path: Path):
    staged, session, session_root, registry_root = _session(tmp_path)
    attach_contributor_extractions(
        session["session_id"], staged, _extractions(),
        access_actor="member-7", root=session_root, registry_root=registry_root,
    )
    suggestions = get_session(session["session_id"], root=session_root)["contributor_suggestions"]
    pouch = next(item for item in suggestions if item["character"] == "pouch_shape")
    result = review_contributor_suggestion(
        session["session_id"], pouch["suggestion_id"],
        decision="reject", reviewer="expert-1", comments="pouch not visible",
        access_actor="member-7", root=session_root, registry_root=registry_root,
    )
    assert result["observation_added"] is False
    stored = get_session(session["session_id"], root=session_root)
    assert stored["observations"] == []
    rejected = next(
        item for item in stored["contributor_suggestions"] if item["character"] == "pouch_shape"
    )
    assert rejected["state"] == "rejected"
    assert rejected["review"]["comments"] == "pouch not visible"
    with pytest.raises(ValueError, match="already has a final"):
        review_contributor_suggestion(
            session["session_id"], pouch["suggestion_id"],
            decision="accept", reviewer="expert-1", certainty="certain",
            access_actor="member-7", root=session_root, registry_root=registry_root,
        )


def test_needs_mapping_suggestion_cannot_be_accepted(tmp_path: Path):
    staged, session, session_root, registry_root = _session(tmp_path)
    attach_contributor_extractions(
        session["session_id"], staged, _extractions(),
        access_actor="member-7", root=session_root, registry_root=registry_root,
    )
    suggestions = get_session(session["session_id"], root=session_root)["contributor_suggestions"]
    unmapped = next(item for item in suggestions if item["character"] == "unregistered_character")
    with pytest.raises(ValueError, match="unambiguous Matrix mapping"):
        review_contributor_suggestion(
            session["session_id"], unmapped["suggestion_id"],
            decision="accept", reviewer="expert-1", certainty="certain",
            access_actor="member-7", root=session_root, registry_root=registry_root,
        )


def test_source_comparison_and_content_addressed_evidence_record(tmp_path: Path):
    staged, session, session_root, registry_root = _session(tmp_path)
    attach_contributor_extractions(
        session["session_id"], staged, _extractions(),
        access_actor="member-7", root=session_root, registry_root=registry_root,
    )
    suggestions = get_session(session["session_id"], root=session_root)["contributor_suggestions"]
    for item in suggestions:
        if item["character"] == "petal_color":
            review_contributor_suggestion(
                session["session_id"], item["suggestion_id"],
                decision="accept", reviewer="expert-1", certainty="probable",
                access_actor="member-7", root=session_root, registry_root=registry_root,
            )
        if item["character"] == "pouch_shape":
            review_contributor_suggestion(
                session["session_id"], item["suggestion_id"],
                decision="revise", reviewer="expert-1", revised_value="pouch",
                certainty="uncertain",
                access_actor="member-7", root=session_root, registry_root=registry_root,
            )

    source_assertions = [
        {
            "subject_id": "world-plants:phragmipedium-kovachii",
            "character": "petal_color",
            "value": "pink",
            "source_ref": "kg:traits:1234",
            "citation": "Govaerts et al., POWO (reviewed)",
        }
    ]
    session_record = get_session(session["session_id"], root=session_root)
    evaluation = evaluate_session(
        session["session_id"], access_actor="member-7",
        root=session_root, registry_root=registry_root,
    )
    comparison = compare_with_governed_sources(
        session_record, evaluation["report"], source_assertions
    )
    petal_rows = [row for row in comparison if row["character"] == "petal_color"]
    assert any(
        row["taxon_id"] == "world-plants:phragmipedium-kovachii"
        and row["source_agreement"] == "supports"
        for row in petal_rows
    )
    assert any(
        row["taxon_id"] == "world-plants:phragmipedium-besseae"
        and row["source_agreement"] == "no_source_evidence"
        for row in petal_rows
    )

    record = build_contributor_evidence_record(
        session["session_id"],
        staged,
        source_assertions=source_assertions,
        access_actor="member-7",
        root=session_root,
        registry_root=registry_root,
    )
    assert record["schema_version"] == "matrix-contributor-evidence/v1"
    assert record["verification_status"] == "unverified_candidate_evidence"
    assert record["registry"]["checksum_sha256"] == session_record["registry"]["checksum_sha256"]
    assert record["contributor_image"]["content_sha256"] == "c" * 64
    assert record["contributor_image"]["permission_grant"] == "cc-by-nc"
    assert record["contributor_image"]["taxon_certainty"] == "unknown"
    assert len(record["reviewed_observations"]) == 2
    assert {item["character"] for item in record["reviewed_observations"]} == {
        "petal_color",
        "pouch_shape",
    }
    audit_states = {item["character"]: item["state"] for item in record["machine_suggestions_audit"]}
    assert audit_states["unregistered_character"] == "needs_mapping"
    assert len(record["checksum_sha256"]) == 64

    rebuilt = build_contributor_evidence_record(
        session["session_id"],
        staged,
        source_assertions=source_assertions,
        access_actor="member-7",
        root=session_root,
        registry_root=registry_root,
    )
    assert rebuilt["checksum_sha256"] == record["checksum_sha256"]
