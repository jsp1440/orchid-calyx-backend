"""Cost-efficiency telemetry for completed Swarm tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TaskEconomics:
    issue_task_id: str
    provider: str
    model: str
    attempts: int
    turns: int | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_seconds: int | None
    actual_cost_usd: Decimal | None
    estimated_cost_usd: Decimal | None
    tests_passed: bool | None
    durable_pr_created: bool
    outcome: str

    @property
    def completed(self) -> bool:
        return self.outcome == "success" and self.durable_pr_created

    @property
    def cost_per_completed_task(self) -> Decimal | None:
        if not self.completed:
            return None
        return self.actual_cost_usd

    def to_jsonable(self) -> dict:
        payload = asdict(self)
        for key in ("actual_cost_usd", "estimated_cost_usd"):
            value = payload[key]
            payload[key] = str(value) if value is not None else None
        payload["completed"] = self.completed
        payload["cost_per_completed_task"] = (
            str(self.cost_per_completed_task)
            if self.cost_per_completed_task is not None
            else None
        )
        return payload
