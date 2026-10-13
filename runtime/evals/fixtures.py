"""Load frozen OC-EVALS-001 fixture sets (task class, cases, strategies, outputs) from JSON."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from runtime.evals.contracts import EvaluationCase, EvaluationTaskClass, StrategySpec


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_task_class(directory: Path) -> EvaluationTaskClass:
    raw = _json(directory / "task_class.json")
    return EvaluationTaskClass(
        task_class_id=raw["task_class_id"],
        version=str(raw["version"]),
        risk_class=raw["risk_class"],
        primary_metric=raw["primary_metric"],
        quality_floor=Decimal(str(raw["quality_floor"])),
        required_evidence=tuple(raw.get("required_evidence") or ()),
        allowed_providers=tuple(raw.get("allowed_providers") or ()),
        max_cost_usd=Decimal(str(raw["max_cost_usd"]))
        if raw.get("max_cost_usd") is not None
        else None,
        promotion_policy=raw.get("promotion_policy", "evidence_backed"),
    )


def load_cases(directory: Path) -> list[EvaluationCase]:
    return [
        EvaluationCase(
            case_id=raw["case_id"],
            version=str(raw["version"]),
            task_class=raw["task_class"],
            inputs=raw["inputs"],
            expectations=raw["expectations"],
            leakage_controls=tuple(raw.get("leakage_controls") or ()),
        )
        for raw in _json(directory / "cases.json")
    ]


def load_strategies(directory: Path) -> dict[str, StrategySpec]:
    return {
        name: StrategySpec(
            strategy_id=raw["strategy_id"],
            version=str(raw["version"]),
            task_class=raw["task_class"],
            model_class=raw.get("model_class"),
            prompt_version=raw.get("prompt_version"),
            toolchain_version=raw.get("toolchain_version"),
            budgets=tuple(tuple(b) for b in raw.get("budgets") or ()),
            policy_gates=tuple(raw.get("policy_gates") or ()),
        )
        for name, raw in _json(directory / "strategies.json").items()
    }


def load_outputs(directory: Path, name: str) -> dict[str, dict[str, Any]]:
    return _json(directory / f"outputs_{name}.json")
