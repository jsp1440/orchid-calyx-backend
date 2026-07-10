from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExecutiveSubsystem:
    id: str
    name: str
    category: str
    status: str
    health: str
    completion: int
    dependencies: list[str]
    blockers: list[str]
    owner_required: bool
    confidence: float
    last_updated: str
    source: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "health": self.health,
            "completion": self.completion,
            "dependencies": self.dependencies,
            "blockers": self.blockers,
            "owner_required": self.owner_required,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
            "source": self.source,
            "summary": self.summary,
            "metrics": self.metrics,
        }

