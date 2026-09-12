from app.evals.evaluators import (
    EvaluatorRegistry,
    EvaluatorSpec,
    FrozenEvaluationOutput,
    boolean_field_evaluator,
    build_default_scientific_registry,
    mandatory_gate_failures,
)
from app.evals.models import MeasurementState


def _output(**overrides):
    payload = {
        "citation_anchor_valid": True,
        "taxonomy_correct": True,
        "evidence_inference_separated": True,
        "counterevidence_preserved": True,
        "uncertainty_explicit": True,
        "unsupported_claims_absent": True,
        "contradictions_preserved": True,
        "abstention_valid": True,
        "protected_locality_safe": True,
        "rights_access_compliant": True,
        "structured_output_valid": True,
        "idempotent": True,
        "precision": 0.95,
        "recall": 0.90,
        "completeness": 0.92,
    }
    payload.update(overrides)
    return FrozenEvaluationOutput(
        output_id="fixture-1",
        task_class_id="literature.answer",
        payload=payload,
        provenance={"source": "botanical-gold-set-fixture"},
    )


def test_default_registry_is_reproducible_for_frozen_output():
    registry = build_default_scientific_registry()
    output = _output()
    first = registry.evaluate(run_identity_fingerprint="run-1", output=output)
    second = registry.evaluate(run_identity_fingerprint="run-1", output=output)
    assert first == second
    assert all(result.evidence["output_fingerprint"] == output.fingerprint for result in first)
    assert mandatory_gate_failures(first) == ()


def test_deliberate_scientific_and_safety_violations_fail_mandatory_gates():
    registry = build_default_scientific_registry()
    results = registry.evaluate(
        run_identity_fingerprint="run-2",
        output=_output(citation_anchor_valid=False, protected_locality_safe=False),
    )
    assert mandatory_gate_failures(results) == ("citation_anchor_valid", "protected_locality_safe")


def test_missing_metric_is_unknown_not_zero():
    registry = build_default_scientific_registry()
    output = _output()
    del output.payload["precision"]
    [result] = registry.evaluate(
        run_identity_fingerprint="run-3",
        output=output,
        evaluator_ids=("precision",),
    )
    assert result.score.state == MeasurementState.UNKNOWN
    assert result.score.value is None
    assert result.passed is None


def test_evaluator_version_changes_registry_fingerprint():
    spec1, fn1 = boolean_field_evaluator(
        evaluator_id="citation_anchor_valid",
        version="1",
        field_name="citation_anchor_valid",
        category="scientific",
        mandatory_gate=True,
    )
    spec2, fn2 = boolean_field_evaluator(
        evaluator_id="citation_anchor_valid",
        version="2",
        field_name="citation_anchor_valid",
        category="scientific",
        mandatory_gate=True,
    )
    first = EvaluatorRegistry()
    first.register(spec1, fn1)
    second = EvaluatorRegistry()
    second.register(spec2, fn2)
    assert first.fingerprint != second.fingerprint


def test_conflicting_same_id_version_registration_is_rejected():
    registry = EvaluatorRegistry()
    spec, fn = boolean_field_evaluator(
        evaluator_id="gate",
        version="1",
        field_name="a",
        category="scientific",
    )
    registry.register(spec, fn)
    conflicting = EvaluatorSpec("gate", "1", "task", False)
    try:
        registry.register(conflicting, fn)
    except ValueError as exc:
        assert "collision" in str(exc)
    else:
        raise AssertionError("expected registration collision")
