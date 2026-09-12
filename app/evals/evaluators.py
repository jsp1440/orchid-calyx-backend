from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import EvaluationResult, MeasurementState, MetricValue, stable_fingerprint


@dataclass(frozen=True, slots=True)
class FrozenEvaluationOutput:
    """Provider-neutral frozen output presented to deterministic evaluators."""

    output_id: str
    task_class_id: str
    payload: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


@dataclass(frozen=True, slots=True)
class EvaluatorSpec:
    evaluator_id: str
    version: str
    category: str
    mandatory_gate: bool = False

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


EvaluatorFn = Callable[
    [FrozenEvaluationOutput], tuple[bool | None, MetricValue, dict[str, Any]]
]


@dataclass
class EvaluatorRegistry:
    _evaluators: dict[tuple[str, str], tuple[EvaluatorSpec, EvaluatorFn]] = field(
        default_factory=dict
    )

    def register(self, spec: EvaluatorSpec, fn: EvaluatorFn) -> None:
        key = (spec.evaluator_id, spec.version)
        existing = self._evaluators.get(key)
        if existing is not None and existing[0] != spec:
            raise ValueError(f"evaluator registration collision: {key}")
        self._evaluators[key] = (spec, fn)

    def specs(self) -> tuple[EvaluatorSpec, ...]:
        return tuple(
            spec
            for spec, _ in sorted(
                self._evaluators.values(),
                key=lambda item: (item[0].evaluator_id, item[0].version),
            )
        )

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint([asdict(spec) for spec in self.specs()])

    def evaluate(
        self,
        *,
        run_identity_fingerprint: str,
        output: FrozenEvaluationOutput,
        evaluator_ids: tuple[str, ...] | None = None,
    ) -> tuple[EvaluationResult, ...]:
        selected = []
        for (evaluator_id, _version), (spec, fn) in sorted(self._evaluators.items()):
            if evaluator_ids is None or evaluator_id in evaluator_ids:
                selected.append((spec, fn))
        results: list[EvaluationResult] = []
        for spec, fn in selected:
            passed, score, evidence = fn(output)
            results.append(
                EvaluationResult(
                    run_identity_fingerprint=run_identity_fingerprint,
                    evaluator_id=spec.evaluator_id,
                    evaluator_version=spec.version,
                    passed=passed,
                    score=score,
                    evidence={
                        "category": spec.category,
                        "mandatory_gate": spec.mandatory_gate,
                        "output_fingerprint": output.fingerprint,
                        **evidence,
                    },
                )
            )
        return tuple(results)


def ratio_metric(value: float) -> MetricValue:
    return MetricValue(MeasurementState.MEASURED, value, "ratio")


def boolean_field_evaluator(
    *,
    evaluator_id: str,
    version: str,
    field_name: str,
    category: str,
    mandatory_gate: bool = False,
) -> tuple[EvaluatorSpec, EvaluatorFn]:
    spec = EvaluatorSpec(
        evaluator_id=evaluator_id,
        version=version,
        category=category,
        mandatory_gate=mandatory_gate,
    )

    def evaluate(output: FrozenEvaluationOutput):
        if field_name not in output.payload:
            return (
                None,
                MetricValue(MeasurementState.UNKNOWN),
                {
                    "field": field_name,
                    "reason": "missing",
                },
            )
        passed = bool(output.payload[field_name])
        return passed, ratio_metric(1.0 if passed else 0.0), {"field": field_name}

    return spec, evaluate


def numeric_ratio_evaluator(
    *,
    evaluator_id: str,
    version: str,
    field_name: str,
    category: str,
    threshold: float | None = None,
    mandatory_gate: bool = False,
) -> tuple[EvaluatorSpec, EvaluatorFn]:
    spec = EvaluatorSpec(
        evaluator_id=evaluator_id,
        version=version,
        category=category,
        mandatory_gate=mandatory_gate,
    )

    def evaluate(output: FrozenEvaluationOutput):
        value = output.payload.get(field_name)
        if not isinstance(value, (int, float)):
            return (
                None,
                MetricValue(MeasurementState.UNKNOWN),
                {
                    "field": field_name,
                    "reason": "missing_or_non_numeric",
                },
            )
        numeric = float(value)
        passed = None if threshold is None else numeric >= threshold
        return (
            passed,
            ratio_metric(numeric),
            {"field": field_name, "threshold": threshold},
        )

    return spec, evaluate


def build_default_scientific_registry() -> EvaluatorRegistry:
    registry = EvaluatorRegistry()
    definitions = (
        ("citation_anchor_valid", "citation_anchor_valid", True),
        ("taxonomy_correct", "taxonomy_correct", True),
        ("evidence_inference_separated", "evidence_inference_separated", True),
        ("counterevidence_preserved", "counterevidence_preserved", False),
        ("uncertainty_explicit", "uncertainty_explicit", False),
        ("unsupported_claims_absent", "unsupported_claims_absent", True),
        ("contradictions_preserved", "contradictions_preserved", False),
        ("abstention_valid", "abstention_valid", False),
        ("protected_locality_safe", "protected_locality_safe", True),
        ("rights_access_compliant", "rights_access_compliant", True),
        ("structured_output_valid", "structured_output_valid", True),
        ("idempotent", "idempotent", True),
    )
    for evaluator_id, field_name, mandatory in definitions:
        spec, fn = boolean_field_evaluator(
            evaluator_id=evaluator_id,
            version="1",
            field_name=field_name,
            category=(
                "scientific"
                if evaluator_id not in {"structured_output_valid", "idempotent"}
                else "task"
            ),
            mandatory_gate=mandatory,
        )
        registry.register(spec, fn)
    for evaluator_id, field_name in (
        ("precision", "precision"),
        ("recall", "recall"),
        ("completeness", "completeness"),
    ):
        spec, fn = numeric_ratio_evaluator(
            evaluator_id=evaluator_id,
            version="1",
            field_name=field_name,
            category="task",
        )
        registry.register(spec, fn)
    return registry


def mandatory_gate_failures(results: tuple[EvaluationResult, ...]) -> tuple[str, ...]:
    failures = []
    for result in results:
        if result.evidence.get("mandatory_gate") and result.passed is not True:
            failures.append(result.evaluator_id)
    return tuple(sorted(failures))
