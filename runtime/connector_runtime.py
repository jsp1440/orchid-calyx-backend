"""BUILD-019 connector runtime scaffolder.

Turns BUILD-018 connector plans into review-ready connector scaffold records.
This is file-backed and safe: it does not mutate Brain tables or call external APIs.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .connector_planner import BrainConnectorPlanner


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "runtime" / "connector_runs"


@dataclass
class ConnectorScaffold:
    adapter_name: str
    module_path: str
    endpoint_prefix: str
    connector_targets: list[str] = field(default_factory=list)
    validation_contract: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)


@dataclass
class ConnectorRun:
    run_id: str
    plan_id: str
    domain: str
    priority: str
    status: str
    generated_at: str
    task: str
    scaffold: ConnectorScaffold
    source: str = "BUILD-019"


class ConnectorRuntimeBuilder:
    """Create deterministic scaffold records from BUILD-018 connector plans."""

    def __init__(self, output_dir: Path | None = None, planner: BrainConnectorPlanner | None = None) -> None:
        self.output_dir = output_dir or OUTPUT_DIR
        self.latest_path = self.output_dir / "latest.json"
        self.history_path = self.output_dir / "history.jsonl"
        self.planner = planner or BrainConnectorPlanner()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_plan(self, plan_id: str, write_cache: bool = True) -> dict[str, Any]:
        plan = self._find_plan(plan_id)
        if plan is None:
            return {"build": "BUILD-019", "status": "not_found", "plan_id": plan_id}
        payload = self._payload([self._run_for_plan(plan)], 1)
        if write_cache:
            self._persist(payload)
        return payload

    def build_queue(self, limit: int | None = None, write_cache: bool = True) -> dict[str, Any]:
        plans = self.planner.latest().get("plans", [])
        if limit is not None:
            plans = plans[:limit]
        payload = self._payload([self._run_for_plan(plan) for plan in plans], len(plans))
        if write_cache:
            self._persist(payload)
        return payload

    def latest(self) -> dict[str, Any]:
        if self.latest_path.exists():
            return json.loads(self.latest_path.read_text(encoding="utf-8"))
        return self.build_queue(write_cache=True)

    def runs(self, limit: int = 20) -> dict[str, Any]:
        rows = self.latest().get("runs", [])[:limit]
        return {"build": "BUILD-019", "count": len(rows), "runs": rows}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        for row in self.latest().get("runs", []):
            if row.get("run_id") == run_id:
                return {"build": "BUILD-019", "run": row}
        return None

    def queue(self, limit: int = 10) -> dict[str, Any]:
        rows = self.latest().get("runs", [])[:limit]
        queue = [
            {
                "queue_rank": index + 1,
                "run_id": row.get("run_id"),
                "plan_id": row.get("plan_id"),
                "domain": row.get("domain"),
                "priority": row.get("priority"),
                "status": row.get("status"),
                "adapter_name": row.get("scaffold", {}).get("adapter_name"),
                "module_path": row.get("scaffold", {}).get("module_path"),
            }
            for index, row in enumerate(rows)
        ]
        return {"build": "BUILD-019", "queue_depth": len(queue), "queue": queue}

    def dashboard(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-019",
            "status": payload.get("status"),
            "summary": payload.get("summary", {}),
            "top_runs": payload.get("runs", [])[:5],
            "next_actions": payload.get("next_actions", [])[:10],
        }

    def _find_plan(self, plan_id: str) -> dict[str, Any] | None:
        for plan in self.planner.latest().get("plans", []):
            if plan.get("plan_id") == plan_id:
                return plan
        return None

    def _run_for_plan(self, plan: dict[str, Any]) -> ConnectorRun:
        domain = str(plan.get("domain", "Connector"))
        slug = self._slug(domain)
        scaffold = ConnectorScaffold(
            adapter_name=f"{domain}ConnectorAdapter".replace(" ", ""),
            module_path=f"runtime/connectors/{slug}_connector.py",
            endpoint_prefix=f"/api/runner/connectors/{slug}",
            connector_targets=list(plan.get("connector_targets", []) or []),
            validation_contract={
                "plan_id": plan.get("plan_id"),
                "requires_provenance": True,
                "requires_source_counts": True,
                "requires_review_queue": True,
                "acceptance": plan.get("validation"),
            },
            next_actions=[
                f"Create {domain} adapter scaffold at runtime/connectors/{slug}_connector.py.",
                f"Expose {domain} connector records through /api/runner/connectors/{slug}.",
                f"Map Brain evidence tables into {domain} source-count and provenance output.",
                f"Add tests for {domain} connector dashboard and validation contract.",
            ],
        )
        return ConnectorRun(
            run_id=f"CR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            plan_id=str(plan.get("plan_id", "UNKNOWN")),
            domain=domain,
            priority=str(plan.get("priority", "HIGH")),
            status="scaffold_ready",
            generated_at=datetime.now(timezone.utc).isoformat(),
            task=str(plan.get("task", "Prepare connector scaffold")),
            scaffold=scaffold,
        )

    def _payload(self, runs: list[ConnectorRun], source_plan_count: int) -> dict[str, Any]:
        rows = [asdict(run) for run in runs]
        return {
            "build": "BUILD-019",
            "status": "connector_scaffolds_ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_build": "BUILD-018",
            "source_plan_count": source_plan_count,
            "summary": {
                "runs": len(rows),
                "critical": sum(1 for row in rows if row.get("priority") == "CRITICAL"),
                "high": sum(1 for row in rows if row.get("priority") == "HIGH"),
                "scaffold_ready": sum(1 for row in rows if row.get("status") == "scaffold_ready"),
            },
            "runs": rows,
            "next_actions": [action for row in rows for action in row.get("scaffold", {}).get("next_actions", [])][:20],
        }

    def _persist(self, payload: dict[str, Any]) -> None:
        self.latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "connector"
