from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .evaluators import EvaluatorRegistry, FrozenEvaluationOutput
from .models import EvaluationCase, EvaluationRun, StrategySpec, stable_fingerprint


class ExperimentBudgetExceeded(RuntimeError):
    pass


class DuplicateExperimentDispatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExperimentBudget:
    max_executions: int = 2
    max_retries_per_strategy: int = 0
    max_cost_usd: float | None = None
    max_latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.max_executions < 1:
            raise ValueError("max_executions must be positive")
        if self.max_retries_per_strategy < 0:
            raise ValueError("max_retries_per_strategy cannot be negative")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ValueError("max_cost_usd cannot be negative")
        if self.max_latency_ms is not None and self.max_latency_ms < 0:
            raise ValueError("max_latency_ms cannot be negative")


@dataclass(frozen=True, slots=True)
class StrategyExecutionArtifact:
    strategy_fingerprint: str
    case_fingerprint: str
    output: FrozenEvaluationOutput
    cost_usd: float | None = None
    latency_ms: int | None = None
    attempts: int = 1
    provenance: dict[str, object] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self)


@dataclass(frozen=True, slots=True)
class StrategyExperimentResult:
    experiment_fingerprint: str
    baseline: StrategyExecutionArtifact
    candidate: StrategyExecutionArtifact
    baseline_run: EvaluationRun
    candidate_run: EvaluationRun
    baseline_result_fingerprints: tuple[str, ...]
    candidate_result_fingerprints: tuple[str, ...]


StrategyExecutor = Callable[[StrategySpec, EvaluationCase], StrategyExecutionArtifact]


@dataclass
class BoundedStrategyExperimentRunner:
    evaluator_registry: EvaluatorRegistry
    executor: StrategyExecutor
    _completed: dict[str, StrategyExperimentResult] = field(default_factory=dict)
    _dispatched_runs: set[str] = field(default_factory=set)
    _suppressed_candidates: set[str] = field(default_factory=set)

    def suppress_candidate(self, material_fingerprint: str) -> None:
        self._suppressed_candidates.add(material_fingerprint)

    def is_suppressed(self, material_fingerprint: str) -> bool:
        return material_fingerprint in self._suppressed_candidates

    def run(
        self,
        *,
        task_class_id: str,
        baseline: StrategySpec,
        candidate: StrategySpec,
        case: EvaluationCase,
        budget: ExperimentBudget,
        provenance: dict[str, object] | None = None,
    ) -> StrategyExperimentResult:
        self._validate_inputs(task_class_id, baseline, candidate, case)

        material_fingerprint = stable_fingerprint(
            {
                "task_class_id": task_class_id,
                "baseline": baseline.fingerprint,
                "candidate": candidate.fingerprint,
                "case": case.fingerprint,
                "evaluators": self.evaluator_registry.fingerprint,
            }
        )
        if material_fingerprint in self._suppressed_candidates:
            raise DuplicateExperimentDispatch("candidate is suppressed for unchanged material fingerprint")
        if material_fingerprint in self._completed:
            return self._completed[material_fingerprint]
        if budget.max_executions < 2:
            raise ExperimentBudgetExceeded("baseline/candidate comparison requires two executions")

        baseline_artifact = self._execute_once(baseline, case)
        candidate_artifact = self._execute_once(candidate, case)
        self._enforce_budget(budget, baseline_artifact, candidate_artifact)

        baseline_run = EvaluationRun(
            run_id=f"eval:{material_fingerprint}:baseline",
            task_class_id=task_class_id,
            case_fingerprint=case.fingerprint,
            strategy_fingerprint=baseline.fingerprint,
            evaluator_set_fingerprint=self.evaluator_registry.fingerprint,
            provenance={"role": "baseline", **(provenance or {})},
        )
        candidate_run = EvaluationRun(
            run_id=f"eval:{material_fingerprint}:candidate",
            task_class_id=task_class_id,
            case_fingerprint=case.fingerprint,
            strategy_fingerprint=candidate.fingerprint,
            evaluator_set_fingerprint=self.evaluator_registry.fingerprint,
            provenance={"role": "candidate", **(provenance or {})},
        )

        baseline_results = self.evaluator_registry.evaluate(
            run_identity_fingerprint=baseline_run.identity_fingerprint,
            output=baseline_artifact.output,
        )
        candidate_results = self.evaluator_registry.evaluate(
            run_identity_fingerprint=candidate_run.identity_fingerprint,
            output=candidate_artifact.output,
        )

        result = StrategyExperimentResult(
            experiment_fingerprint=material_fingerprint,
            baseline=baseline_artifact,
            candidate=candidate_artifact,
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            baseline_result_fingerprints=tuple(item.fingerprint for item in baseline_results),
            candidate_result_fingerprints=tuple(item.fingerprint for item in candidate_results),
        )
        self._completed[material_fingerprint] = result
        return result

    def _execute_once(self, strategy: StrategySpec, case: EvaluationCase) -> StrategyExecutionArtifact:
        dispatch_key = stable_fingerprint(
            {"strategy": strategy.fingerprint, "case": case.fingerprint}
        )
        if dispatch_key in self._dispatched_runs:
            raise DuplicateExperimentDispatch("duplicate model/tool dispatch suppressed")
        artifact = self.executor(strategy, case)
        if artifact.strategy_fingerprint != strategy.fingerprint:
            raise ValueError("executor returned stale or mismatched strategy fingerprint")
        if artifact.case_fingerprint != case.fingerprint:
            raise ValueError("executor returned stale or mismatched case fingerprint")
        self._dispatched_runs.add(dispatch_key)
        return artifact

    @staticmethod
    def _validate_inputs(
        task_class_id: str,
        baseline: StrategySpec,
        candidate: StrategySpec,
        case: EvaluationCase,
    ) -> None:
        for strategy in (baseline, candidate):
            if strategy.task_class_id != task_class_id:
                raise ValueError("strategy task class does not match experiment task class")
        if case.task_class_id != task_class_id:
            raise ValueError("evaluation case task class does not match experiment task class")
        if baseline.fingerprint == candidate.fingerprint:
            raise ValueError("candidate must materially differ from baseline")

    @staticmethod
    def _enforce_budget(
        budget: ExperimentBudget,
        baseline: StrategyExecutionArtifact,
        candidate: StrategyExecutionArtifact,
    ) -> None:
        artifacts = (baseline, candidate)
        if any(item.attempts > 1 + budget.max_retries_per_strategy for item in artifacts):
            raise ExperimentBudgetExceeded("retry budget exceeded")
        if budget.max_cost_usd is not None:
            known_costs = [item.cost_usd for item in artifacts if item.cost_usd is not None]
            if known_costs and sum(known_costs) > budget.max_cost_usd:
                raise ExperimentBudgetExceeded("cost budget exceeded")
        if budget.max_latency_ms is not None:
            known_latency = [item.latency_ms for item in artifacts if item.latency_ms is not None]
            if known_latency and sum(known_latency) > budget.max_latency_ms:
                raise ExperimentBudgetExceeded("latency budget exceeded")
