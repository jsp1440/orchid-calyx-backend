from app.canonical_brain.constitution import (
    BuildAdmissionRequest,
    evaluate_build_admission,
)


def _request(**overrides: object) -> BuildAdmissionRequest:
    payload = {
        "build_id": "build:test-001",
        "architecture_id": "architecture:brain",
        "intent_ids": ["intent:enable-governed-autonomy"],
        "decision_ids": ["decision:brain"],
        "source_uris": ["docs/architecture/BUILD-BRAIN-105-CONSTITUTION.md"],
        "validation_plan_ids": ["validation:brain-105"],
        "deterministic_outputs": True,
        "preserves_provenance": True,
        "separates_evidence_from_inference": True,
    }
    payload.update(overrides)
    return BuildAdmissionRequest(**payload)


def test_compliant_build_is_admitted() -> None:
    result = evaluate_build_admission(_request())
    assert result.status == "admitted"
    assert result.findings == []


def test_unsafe_authority_requests_are_blocked() -> None:
    result = evaluate_build_admission(_request(publication_requested=True, deployment_requested=True, merge_requested=True, production_graph_mutation_requested=True))
    assert result.status == "blocked"
    assert {item.rule_id for item in result.findings} == {"OC-CONST-004", "OC-CONST-005", "OC-CONST-006", "OC-CONST-007"}


def test_missing_scientific_safeguards_are_blocked() -> None:
    result = evaluate_build_admission(_request(deterministic_outputs=False, preserves_provenance=False, separates_evidence_from_inference=False))
    assert result.status == "blocked"
    assert {item.rule_id for item in result.findings} == {"OC-CONST-001", "OC-CONST-002", "OC-CONST-003"}
