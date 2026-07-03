from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HealthCheckResult:
    component: str
    status: str
    message: str
    checked_at: str = field(default_factory=utc_now)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GovernanceReview:
    allowed: bool
    autonomy_level: int
    requires_human_approval: bool
    reasons: List[str]
    reviewed_at: str = field(default_factory=utc_now)


@dataclass
class MissionReport:
    generated_at: str
    overall_status: str
    health: List[HealthCheckResult]
    top_bottleneck: Optional[str]
    recommended_goal: Optional[str]
    governance: GovernanceReview
    next_actions: List[str]
