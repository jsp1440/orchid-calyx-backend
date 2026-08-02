"""Deterministic, read-only self-audit primitives for the Calyx runtime.

CALYX-RUNTIME-001A deliberately stops at observation, scoring, and work-item
preparation. It cannot merge, deploy, publish, delete, send externally, or
change governance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

SEVERITIES = {"info": 10, "low": 25, "medium": 50, "high": 75, "critical": 100}
PROHIBITED_AUTONOMOUS_ACTIONS = {
    "merge",
    "deploy",
    "publish",
    "delete",
    "external_send",
    "change_permissions",
    "change_governance",
}


@dataclass(frozen=True)
class AuditSignal:
    source: str
    check: str
    status: str
    severity: str = "info"
    confidence: float = 1.0
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuditFinding:
    finding_key: str
    source: str
    title: str
    severity: str
    confidence: float
    priority: int
    recommended_action: str
    requires_human_approval: bool
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditReport:
    generated_at: str
    status: str
    findings: tuple[AuditFinding, ...]
    inspected_sources: tuple[str, ...]
    autonomous_changes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "status": self.status,
            "findings": [finding.as_dict() for finding in self.findings],
            "inspected_sources": list(self.inspected_sources),
            "autonomous_changes": list(self.autonomous_changes),
        }


class SelfAuditEngine:
    """Convert trusted runtime signals into prioritized, reviewable findings."""

    unhealthy_statuses = {"failed", "error", "blocked", "stale", "degraded", "missing"}

    def audit(self, signals: Iterable[AuditSignal]) -> AuditReport:
        normalized = tuple(signals)
        findings = tuple(
            sorted(
                (self._finding(signal) for signal in normalized if self._is_finding(signal)),
                key=lambda finding: (-finding.priority, finding.finding_key),
            )
        )
        sources = tuple(sorted({signal.source for signal in normalized}))
        return AuditReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            status="attention_required" if findings else "healthy",
            findings=findings,
            inspected_sources=sources,
            autonomous_changes=(),
        )

    def _is_finding(self, signal: AuditSignal) -> bool:
        return signal.status.strip().lower() in self.unhealthy_statuses

    def _finding(self, signal: AuditSignal) -> AuditFinding:
        severity = signal.severity.strip().lower()
        if severity not in SEVERITIES:
            raise ValueError(f"unsupported severity: {signal.severity}")
        confidence = max(0.0, min(1.0, float(signal.confidence)))
        base = SEVERITIES[severity]
        priority = min(100, round(base * (0.75 + 0.25 * confidence)))
        action = self._recommended_action(signal)
        return AuditFinding(
            finding_key=f"{signal.source}:{signal.check}",
            source=signal.source,
            title=f"{signal.check} is {signal.status}",
            severity=severity,
            confidence=confidence,
            priority=priority,
            recommended_action=action,
            requires_human_approval=action in PROHIBITED_AUTONOMOUS_ACTIONS,
            evidence={"status": signal.status, "details": signal.details or {}},
        )

    @staticmethod
    def _recommended_action(signal: AuditSignal) -> str:
        details = signal.details or {}
        proposed = str(details.get("recommended_action", "prepare_draft_work_item")).strip().lower()
        return proposed or "prepare_draft_work_item"


def build_operational_briefing(report: AuditReport) -> dict[str, Any]:
    """Create the Mission Control payload without executing any finding."""

    return {
        "generated_at": report.generated_at,
        "overall_status": report.status,
        "inspected_sources": list(report.inspected_sources),
        "finding_count": len(report.findings),
        "top_findings": [finding.as_dict() for finding in report.findings[:10]],
        "execution_policy": {
            "mode": "observe_and_prepare_only",
            "automatic_merge": False,
            "automatic_deploy": False,
            "automatic_scientific_publication": False,
            "external_communications": False,
        },
    }
