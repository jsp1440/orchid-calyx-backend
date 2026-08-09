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
    result = evaluate_build_admission(
        _request(
            publication_requested=True,
            deployment_requested=True,
            merge_requested=True,
            production_graph_mutation_requested=True,
        )
    )
    assert result.status == "blocked"
    assert {item.rule_id for item in result.findings} == {
        "OC-CONST-004",
        "OC-CONST-005",
        "OC-CONST-006",
        "OC-CONST-007",
    }


def test_missing_scientific_safeguards_are_blocked() -> None:
    result = evaluate_build_admission(
        _request(
            deterministic_outputs=False,
            preserves_provenance=False,
            separates_evidence_from_inference=False,
        )
    )
    assert result.status == "blocked"
    assert {item.rule_id for item in result.findings} == {
        "OC-CONST-001",
        "OC-CONST-002",
        "OC-CONST-003",
    }


def test_ci_circuit_breaker_blocks_workflow_expansion_after_three_pre_step_failures() -> None:
    result = evaluate_build_admission(
        _request(
            ci_infrastructure_status="degraded",
            equivalent_pre_step_failures_60m=3,
            workflow_triggering_change_requested=True,
        )
    )
    assert result.status == "blocked"
    assert {item.rule_id for item in result.findings} == {"OC-CONST-008"}


def test_ci_unavailable_blocks_workflow_expansion_even_before_threshold() -> None:
    result = evaluate_build_admission(
        _request(
            ci_infrastructure_status="unavailable",
            equivalent_pre_step_failures_60m=1,
            workflow_triggering_change_requested=True,
        )
    )
    assert result.status == "blocked"
    assert {item.rule_id for item in result.findings} == {"OC-CONST-008"}


def test_infrastructure_repair_is_allowed_while_circuit_breaker_is_open() -> None:
    result = evaluate_build_admission(
        _request(
            ci_infrastructure_status="unavailable",
            equivalent_pre_step_failures_60m=20,
            workflow_triggering_change_requested=True,
            infrastructure_repair_requested=True,
        )
    )
    assert result.status == "admitted"
    assert result.findings == []


def test_repeated_recovery_probe_requires_material_change_evidence() -> None:
    blocked = evaluate_build_admission(
        _request(
            ci_infrastructure_status="unavailable",
            equivalent_pre_step_failures_60m=20,
            diagnostic_recovery_probe_requested=True,
        )
    )
    assert blocked.status == "blocked"
    assert {item.rule_id for item in blocked.findings} == {"OC-CONST-009"}

    allowed = evaluate_build_admission(
        _request(
            ci_infrastructure_status="unavailable",
            equivalent_pre_step_failures_60m=20,
            diagnostic_recovery_probe_requested=True,
            material_recovery_evidence_present=True,
        )
    )
    assert allowed.status == "admitted"
    assert allowed.findings == []


def test_degraded_ci_below_threshold_warns_without_blocking() -> None:
    result = evaluate_build_admission(
        _request(
            ci_infrastructure_status="degraded",
            equivalent_pre_step_failures_60m=2,
        )
    )
    assert result.status == "admitted"
    assert [item.rule_id for item in result.findings] == ["OC-CONST-W01"]
