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
    data_coverage: int = 0
    evidence_quality: int = 0
    automation_readiness: int = 0
    integration_readiness: int = 0
    operational_reliability: int = 0
    active_jobs: int = 0
    failures: list[str] = field(default_factory=list)
    recommended_action: str = ""
    source_record_counts: dict[str, int] = field(default_factory=dict)
    telemetry_freshness: str = "unavailable"

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
            "data_coverage": self.data_coverage,
            "evidence_quality": self.evidence_quality,
            "automation_readiness": self.automation_readiness,
            "integration_readiness": self.integration_readiness,
            "operational_reliability": self.operational_reliability,
            "active_jobs": self.active_jobs,
            "failures": self.failures,
            "recommended_action": self.recommended_action,
            "source_record_counts": self.source_record_counts,
            "telemetry_freshness": self.telemetry_freshness,
        }

