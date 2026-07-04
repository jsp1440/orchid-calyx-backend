"""BUILD-018 connector planner.

This module converts BUILD-017 knowledge-gap diagnostics into a practical
connector implementation plan. It is intentionally file-backed and safe to run
on Render without DATABASE_URL.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .knowledge_gap_diagnostics import KnowledgeGapDiagnosticsEngine


REPO_ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PLAN_DIR = REPO_ROOT / "runtime" / "connector_plans"
LATEST_PATH = CONNECTOR_PLAN_DIR / "latest.json"


CONNECTOR_HINTS: dict[str, list[str]] = {
    "Taxonomy": ["World Plants", "GBIF Backbone", "POWO/IPNI", "taxonomic resolver"],
    "Images": ["iNaturalist media", "GBIF media", "image quality filter", "trusted image cache"],
    "Occurrences": ["GBIF", "iNaturalist", "herbarium georeference", "Atlas occurrence bridge"],
    "Pollination": ["GloBI", "Global Pollination dataset", "literature interaction extraction"],
    "Mycorrhiza": ["mycorrhizal literature", "fungal sequence records", "association evidence table"],
    "Conservation": ["IUCN", "project species lists", "habitat/climate tables"],
    "Literature": ["reference documents", "citation graph", "claims extraction"],
    "Traits": ["TraitBank/EOL", "orchid trait tables", "phenology observations"],
    "Governance": ["review queue", "provenance ledger", "audit tables"],
}


@dataclass
class ConnectorPlan:
    plan_id: str
    domain: str
    priority: str
    source_gap_id: str
    connector_targets: list[str] = field(default_factory=list)
    task: str = ""
    expected_output: str = ""
    validation: str = ""
    source: str = "BUILD-018"


class BrainConnectorPlanner:
    """Plan connector work from current knowledge-gap diagnostics."""

    def __init__(
        self,
        output_dir: Path | None = None,
        diagnostic_engine: KnowledgeGapDiagnosticsEngine | None = None,
    ) -> None:
        self.output_dir = output_dir or CONNECTOR_PLAN_DIR
        self.latest_path = self.output_dir / "latest.json"
        self.diagnostic_engine = diagnostic_engine or KnowledgeGapDiagnosticsEngine()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, write_cache: bool = True) -> dict[str, Any]:
        diagnostics = self.diagnostic_engine.latest()
        gaps = diagnostics.get("gaps", [])
        plans = [self._plan_for_gap(gap, index + 1) for index, gap in enumerate(gaps)]
        grouped = self._group_by_domain(plans)
        payload = {
            "build": "BUILD-018",
            "status": "connector_plans_ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_build": diagnostics.get("build"),
            "source_status": diagnostics.get("status"),
            "brain": diagnostics.get("brain", {}),
            "summary": {
                "plans": len(plans),
                "domains": len(grouped),
                "critical": sum(1 for plan in plans if plan.priority == "CRITICAL"),
                "high": sum(1 for plan in plans if plan.priority == "HIGH"),
            },
            "plans": [asdict(plan) for plan in plans],
            "domains": grouped,
            "top_actions": [plan.task for plan in plans[:5]],
        }
        if write_cache:
            self.latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def latest(self) -> dict[str, Any]:
        if self.latest_path.exists():
            return json.loads(self.latest_path.read_text(encoding="utf-8"))
        return self.generate(write_cache=True)

    def domains(self) -> dict[str, Any]:
        payload = self.latest()
        return {"build": "BUILD-018", "count": len(payload.get("domains", {})), "domains": payload.get("domains", {})}

    def queue(self, limit: int = 10) -> dict[str, Any]:
        plans = self.latest().get("plans", [])[:limit]
        queue = [
            {
                "queue_rank": index + 1,
                "plan_id": plan.get("plan_id"),
                "domain": plan.get("domain"),
                "priority": plan.get("priority"),
                "task": plan.get("task"),
                "connector_targets": plan.get("connector_targets", []),
            }
            for index, plan in enumerate(plans)
        ]
        return {"build": "BUILD-018", "queue_depth": len(queue), "queue": queue}

    def dashboard(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-018",
            "status": payload.get("status"),
            "brain": payload.get("brain", {}),
            "summary": payload.get("summary", {}),
            "top_plans": payload.get("plans", [])[:5],
            "top_actions": payload.get("top_actions", []),
        }

    def _plan_for_gap(self, gap: dict[str, Any], rank: int) -> ConnectorPlan:
        domain = str(gap.get("domain", "Governance"))
        targets = CONNECTOR_HINTS.get(domain, ["Brain table bridge", "runtime validator", "review queue"])
        priority = str(gap.get("priority", "HIGH"))
        gap_id = str(gap.get("gap_id", f"GAP-{rank:03d}"))
        return ConnectorPlan(
            plan_id=f"CP-{rank:03d}-{domain.upper().replace(' ', '-')}",
            domain=domain,
            priority=priority,
            source_gap_id=gap_id,
            connector_targets=targets,
            task=f"Build {domain} connector plan from {gap_id}: {gap.get('proposed_action', 'connect evidence sources')}",
            expected_output=f"Review-ready {domain} connector output with provenance, validation status, and queued next actions.",
            validation=f"Endpoint returns {domain} evidence, source counts, and no unhandled runtime import errors.",
        )

    def _group_by_domain(self, plans: list[ConnectorPlan]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for plan in plans:
            grouped.setdefault(plan.domain, []).append(asdict(plan))
        return grouped
