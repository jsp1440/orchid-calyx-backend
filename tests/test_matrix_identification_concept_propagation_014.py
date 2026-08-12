from runtime.matrix_identification_explanation import build_explanation_evidence
from runtime.matrix_identification_report import build_report_core

CONCEPT_ID = "11111111-1111-4111-8111-111111111111"


def _evaluation():
    next_observation = {
        "character": "spur_length_mm",
        "label": "Spur length",
        "concept_id": CONCEPT_ID,
        "matrix_weight": 3,
        "selection_score": 1.5,
    }
    return {
        "session": {
            "session_id": "session-1",
            "revision": 2,
            "actor": "owner",
            "registry": {
                "registry_id": "angraecum",
                "version": "2-reviewed",
                "checksum_sha256": "registry-digest",
                "publication_state": "review_required",
                "scope": {"genus": "Angraecum"},
            },
            "observations": [],
            "vision_suggestions": [],
        },
        "report": {
            "registry": {
                "registry_id": "angraecum",
                "version": "2-reviewed",
                "checksum_sha256": "registry-digest",
                "publication_state": "review_required",
                "scope": {"genus": "Angraecum"},
            },
            "candidates": [],
            "observation_count": 0,
            "compared_character_count": 0,
            "disclaimer": "candidate-ranking evidence only",
        },
        "next_observation": next_observation,
    }


def test_next_observation_concept_identity_reaches_calyx_evidence_packet():
    evidence = build_explanation_evidence(
        _evaluation(),
        audience="expert",
        focus="next_observation",
    )
    assert evidence["next_observation"]["concept_id"] == CONCEPT_ID
    assert evidence["authority"]["calyx_may_change_next_observation"] is False


def test_next_observation_concept_identity_is_frozen_into_reproducible_report():
    report = build_report_core(_evaluation())
    assert report["next_observation"]["concept_id"] == CONCEPT_ID
    assert report["registry"]["checksum_sha256"] == "registry-digest"
