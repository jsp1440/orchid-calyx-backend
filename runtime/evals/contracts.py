"""OC-EVALS-001 canonical records (EVALS-001A).

Names and decision values follow the Brain blueprint
``14_ENGINEERING/OC-EVALS-001-self-improving-agent-evaluation-blueprint.md``.
Records are immutable, JSON-serialisable and fingerprinted so that a replay of
the same strategy, cases, evaluators and outputs is recognisably the same run.

Unknown measurements remain unknown: a metric that could not be measured has
``state = UNMEASURED`` (or ``PARKED`` when NO_API_MODE withheld a provider
evaluator) and ``score = None``. It is never coerced to zero.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

SCHEMA_PREFIX = "oc.evals"


def fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class MeasurementState(StrEnum):
    MEASURED = "MEASURED"
    UNMEASURED = "UNMEASURED"
    PARKED = "PARKED"  # provider-requiring evaluator withheld by NO_API_MODE


class DecisionKind(StrEnum):
    PROMOTE = "PROMOTE"
    KEEP_BASELINE = "KEEP_BASELINE"
    LIMITED_CANARY = "LIMITED_CANARY"
    REJECT_QUALITY = "REJECT_QUALITY"
    REJECT_SAFETY = "REJECT_SAFETY"
    REJECT_COST = "REJECT_COST"
    REJECT_INSTABILITY = "REJECT_INSTABILITY"
    UNMEASURED = "UNMEASURED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class EvaluationTaskClass:
    task_class_id: str
    version: str
    risk_class: str  # "low" | "moderate" | "high"
    primary_metric: str
    quality_floor: Decimal
    required_evidence: tuple[str, ...] = ()
    allowed_providers: tuple[str, ...] = ()
    max_cost_usd: Decimal | None = None
    promotion_policy: str = "evidence_backed"

    def __post_init__(self) -> None:
        if self.risk_class not in {"low", "moderate", "high"}:
            raise ValueError(f"unknown risk_class: {self.risk_class}")
        if not Decimal(0) <= self.quality_floor <= Decimal(1):
            raise ValueError("quality_floor must be within [0, 1]")

    @property
    def identity(self) -> str:
        return f"{self.task_class_id}@{self.version}"


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    version: str
    task_class: str  # EvaluationTaskClass.identity
    model_class: str | None = None
    prompt_version: str | None = None
    toolchain_version: str | None = None
    budgets: tuple[tuple[str, str], ...] = ()
    policy_gates: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return f"{self.strategy_id}@{self.version}"

    @property
    def provenance_fingerprint(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    version: str
    task_class: str
    inputs: dict[str, Any]
    expectations: dict[str, Any]
    leakage_controls: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class EvaluationResult:
    """One evaluator's verdict on one case (per-metric score)."""

    case_id: str
    metric_id: str
    evaluator_version: str
    state: MeasurementState
    score: Decimal | None
    passed: bool | None
    gate: bool
    reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state is not MeasurementState.MEASURED and (
            self.score is not None or self.passed is not None
        ):
            raise ValueError("an unmeasured result cannot carry a score or verdict")
        if self.score is not None and not Decimal(0) <= self.score <= Decimal(1):
            raise ValueError("score must be within [0, 1]")

    @property
    def gate_failed(self) -> bool:
        return self.gate and self.passed is False


@dataclass(frozen=True)
class MetricSummary:
    metric_id: str
    measured_cases: int
    unmeasured_cases: int
    mean_score: Decimal | None


@dataclass(frozen=True)
class EvaluationRun:
    run_id: str
    task_class: str
    strategy: str
    strategy_fingerprint: str
    case_set_fingerprint: str
    evaluator_versions: tuple[tuple[str, str], ...]
    code_sha: str | None
    results: tuple[EvaluationResult, ...]
    summaries: tuple[MetricSummary, ...]
    estimated_cost_usd: Decimal | None
    cost_basis: str
    latency_seconds: Decimal | None
    no_api_mode: bool
    outputs_fingerprint: str

    def summary(self, metric_id: str) -> MetricSummary | None:
        return next((s for s in self.summaries if s.metric_id == metric_id), None)

    @property
    def gate_failures(self) -> tuple[EvaluationResult, ...]:
        return tuple(r for r in self.results if r.gate_failed)

    def to_jsonable(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=str))


@dataclass(frozen=True)
class StrategyDecision:
    decision: DecisionKind
    task_class: str
    baseline: str
    candidate: str
    rationale: tuple[str, ...]
    thresholds: dict[str, str]
    evidence: tuple[str, ...]  # EvaluationRun ids
    scope: str
    rollback_target: str
    review_trigger: str
    requires_human_approval: bool = False
    suppressed_rediscovery: bool = False
    # An eval outcome never merges, deploys, publishes or activates a paid provider.
    authorizes: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.authorizes:
            raise ValueError(
                "a strategy decision authorizes nothing outside the evaluation layer"
            )

    def to_jsonable(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=str))
