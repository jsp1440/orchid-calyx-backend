from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class MeasurementState(StrEnum):
    MEASURED = "MEASURED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class StrategyDecisionState(StrEnum):
    PROMOTE = "PROMOTE"
    KEEP_BASELINE = "KEEP_BASELINE"
    LIMITED_CANARY = "LIMITED_CANARY"
    REJECT_QUALITY = "REJECT_QUALITY"
    REJECT_SAFETY = "REJECT_SAFETY"
    REJECT_COST = "REJECT_COST"
    REJECT_INSTABILITY = "REJECT_INSTABILITY"
    UNMEASURED = "UNMEASURED"
    SUPERSEDED = "SUPERSEDED"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_fingerprint(value: Any) -> str:
    if hasattr(value, "to_fingerprint_payload"):
        payload = value.to_fingerprint_payload()
    elif hasattr(value, "__dataclass_fields__"):
        payload = asdict(value)
    else:
        payload = value
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MetricValue:
    state: MeasurementState
    value: float | int | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.state == MeasurementState.MEASURED and self.value is None:
            raise ValueError("MEASURED metric requires value")
        if self.state != MeasurementState.MEASURED and self.value is not None:
            raise ValueError(
                "unavailable/unknown metric must not carry a numeric value"
            )


@dataclass(frozen=True, slots=True)
class EvaluationTaskClass:
    task_class_id: str
    version: str
    risk_class: str
    primary_metric: str
    mandatory_gate_ids: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


@dataclass(frozen=True, slots=True)
class StrategySpec:
    strategy_id: str
    version: str
    task_class_id: str
    implementation_ref: str
    config: dict[str, Any] = field(default_factory=dict)
    evaluator_versions: dict[str, str] = field(default_factory=dict)
    model_ref: str | None = None
    provider_ref: str | None = None

    def to_fingerprint_payload(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "task_class_id": self.task_class_id,
            "implementation_ref": self.implementation_ref,
            "config": self.config,
            "evaluator_versions": self.evaluator_versions,
            "model_ref": self.model_ref,
            "provider_ref": self.provider_ref,
        }

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    version: str
    task_class_id: str
    input_ref: str
    expected_ref: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    run_id: str
    task_class_id: str
    case_fingerprint: str
    strategy_fingerprint: str
    evaluator_set_fingerprint: str
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def identity_fingerprint(self) -> str:
        return stable_fingerprint(
            {
                "task_class_id": self.task_class_id,
                "case_fingerprint": self.case_fingerprint,
                "strategy_fingerprint": self.strategy_fingerprint,
                "evaluator_set_fingerprint": self.evaluator_set_fingerprint,
            }
        )


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    run_identity_fingerprint: str
    evaluator_id: str
    evaluator_version: str
    passed: bool | None
    score: MetricValue
    latency_ms: MetricValue = field(
        default_factory=lambda: MetricValue(MeasurementState.UNKNOWN)
    )
    cost_usd: MetricValue = field(
        default_factory=lambda: MetricValue(MeasurementState.UNKNOWN)
    )
    usage_units: MetricValue = field(
        default_factory=lambda: MetricValue(MeasurementState.UNKNOWN)
    )
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    decision_id: str
    task_class_id: str
    baseline_strategy_fingerprint: str
    candidate_strategy_fingerprint: str
    state: StrategyDecisionState
    evaluation_fingerprints: tuple[str, ...]
    decision_policy_version: str
    rollback_strategy_fingerprint: str | None
    scope: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    supersedes_decision_id: str | None = None

    def __post_init__(self) -> None:
        if (
            self.state
            in {StrategyDecisionState.PROMOTE, StrategyDecisionState.LIMITED_CANARY}
            and not self.rollback_strategy_fingerprint
        ):
            raise ValueError(
                "promote/canary decisions require rollback strategy identity"
            )

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)
