from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationTaskClass,
    StrategyDecision,
    StrategySpec,
)


@dataclass
class InMemoryEvaluationRepository:
    task_classes: dict[str, EvaluationTaskClass] = field(default_factory=dict)
    strategies: dict[str, StrategySpec] = field(default_factory=dict)
    cases: dict[str, EvaluationCase] = field(default_factory=dict)
    runs: dict[str, EvaluationRun] = field(default_factory=dict)
    results: dict[str, EvaluationResult] = field(default_factory=dict)
    decisions: dict[str, StrategyDecision] = field(default_factory=dict)

    def put_task_class(self, item: EvaluationTaskClass) -> EvaluationTaskClass:
        return self._put(self.task_classes, item.fingerprint, item)

    def put_strategy(self, item: StrategySpec) -> StrategySpec:
        return self._put(self.strategies, item.fingerprint, item)

    def put_case(self, item: EvaluationCase) -> EvaluationCase:
        return self._put(self.cases, item.fingerprint, item)

    def put_run(self, item: EvaluationRun) -> EvaluationRun:
        return self._put(self.runs, item.identity_fingerprint, item)

    def put_result(self, item: EvaluationResult) -> EvaluationResult:
        return self._put(self.results, item.fingerprint, item)

    def put_decision(self, item: StrategyDecision) -> StrategyDecision:
        existing = self.decisions.get(item.decision_id)
        if existing is not None and existing != item:
            raise ValueError(f"decision_id collision: {item.decision_id}")
        self.decisions[item.decision_id] = item
        return item

    @staticmethod
    def _put(store: dict[str, object], key: str, item):
        existing = store.get(key)
        if existing is not None and existing != item:
            raise ValueError(f"fingerprint collision for {key}")
        store[key] = item
        return item
