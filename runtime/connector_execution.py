"""BUILD-019 connector execution engine.

BUILD-018 produces connector plans. BUILD-019 turns those plans into
review-ready execution records and deterministic connector scaffolds that can be
inspected through the runtime API before any real data mutation is attempted.

This build is intentionally file-backed and safe on Render. It does not write to
Brain tables or call external APIs. It prepares implementation scaffolds,
validation contracts, and queued next actions for each connector plan.
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
CONNECTOR_EXECUTION_DIR = REPO_ROOT / "runtime" / "connector_executions"
LATEST_PATH = CONNECTOR_EXECUTION_DIR / "latest.json"
HISTORY_PATH = CONNECTOR_EXECUTION_DIR / "history.jsonl"


@dataclass
class ConnectorScaffold:
    adapter_name: str
    module_path: str
    endpoint_prefix: str
    source_tables: list[dict[str, Any]] = field(default_factory=list)
    connector_targets: list[str] = field(default_factory=list)
    validation_contract: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)


@dataclass
class ConnectorExecution:
    execution_id: str
    plan_id: str
    domain: str
    priority: str
    status: str
    started_at: str
    completed_at: str
    task: str
    scaffold: ConnectorScaffold
    source: str = "BUILD-019"


class ConnectorExecutionEngine:
    """Prepare deterministic runtime connector scaffolds from BUILD-018 plans."""

    def __init__(
        self,
        output_dir: Path | None = None,
        planner: BrainConnectorPlanner | None = None,
    ) -> None:
        self.output_dir = output_dir or CONNECTOR_EXECUTION_DIR
        self.latest_path = self.output_dir / "latest.json"
        self.history_path = self.output_dir / "history.jsonl"
        self.planner = planner or BrainConnectorPlanner()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def execute_plan(self, plan_id: str, write_cache: bool = True) -> dict[str, Any]:
        plan = self._find_plan(plan_id)
        if plan is None:
            return {"build": "BUILD-019", "status": "not_found", "plan_id": plan_id}
        execution = self._execution_for_plan(plan)
        payload = self._payload([execution], source_plan_count=1)
        if write_cache:
            self._persist(payload)
        return payload

    def execute_queue(self, limit: int | None = None, write_cache: bool = True) -> dict[str, Any]:
        plans = self.planner.latest().get("plans", [])
        if limit is not None:
            plans = plans[:limit]
        executions = [self._execution_for_plan(plan) for plan in plans]
        payload = self._payload(executions, source_plan_count=len(plans))
        if write_cache:
            self._persist(payload)
        return payload

    def latest(self) -> dict[str, Any]:
        if self.latest_path.exists():
            return json.loads(self.latest_path.read_text(encoding="utf-8"))
        return self.execute_queue(write_cache=True)

    def list_executions(self, limit: int = 20) -> dict[str, Any]:
        payload = self.latest()
        executions = payload.get("executions", [])[:limit]
        return {"build": "BUILD-019", "count": len(executions), "executions": executions}

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        for execution in self.latest().get("executions", []):
            if execution.get("execution_id") == execution_id:
                return {"build": "BUILD-019", "execution": execution}
        return None

    def queue(self, limit: int = 10) -> dict[str, Any]:
        executions = self.latest().get("executions", [])[:limit]
        queue = [
            {
                "queue_rank": index + 1,
                "execution_id": item.get("execution_id"),
                "plan_id": item.get("plan_id"),
                "domain": item.get("domain"),
                "priority": item.get("priority"),
                "status": item.get("status"),
                "adapter_name": item.get("scaffold", {}).get("adapter_name"),
                "module_path": item.get("scaffold", {}).get("module_path"),
            }
            for index, item in enumerate(executions)
        ]
        return {"build": "BUILD-019", "queue_depth": len(queue), "queue": queue}

    def dashboard(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-019",
            "status": payload.get("status"),
            "summary": payload.get("summary", {}),
            "top_executions": payload.get("executions", [])[:5],
            "next_actions": payload.get("next_actions", [])[:10],
        }

    def _find_plan(self, plan_id: str) -> dict[str, Any] | None:
        for plan in self.planner.latest().get("plans", []):
            if plan.get("plan_id") == plan_id:
                return plan
        return None

    def _execution_for_plan(self, plan: dict[str, Any]) -> ConnectorExecution:
        now = datetime.now(timezone.utc).isoformat()
        domain = str(plan.get("domain", "Connector"))
        scaffold = self._scaffold_for_plan(plan)
        return ConnectorExecution(
            execution_id=f"CX-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            plan_id=str(plan.get("plan_id", "UNKNOWN")),
            domain=domain,
            priority=str(plan.get("priority", "HIGH")),
            status="scaffold_ready",
            started_at=now,
            completed_at=now,
            task=str(plan.get("task", "Prepare connector scaffold")),
            scaffold=scaffold,
        )

    def _scaffold_for_plan(self, plan: dict[str, Any]) -> ConnectorScaffold:
        domain = str(plan.get("domain", "Connector"))
        slug = self._slug(domain)
        targets = list(plan.get("connector_targets", []) or [])
        return ConnectorScaffold(
            adapter_name=f"{domain}ConnectorAdapter".replace(" ", ""),
            module_path=f"runtime/connectors/{slug}_connector.py",
            endpoint_prefix=f"/api/runner/connectors/{slug}",
            connector_targets=targets,
            validation_contract={
                "plan_id": plan.get("plan_id"),
                "requires_provenance": True,
                "requires_source_counts": True,
                "requires_review_queue": True,
                "requires_no_unhandled_import_errors": True,
                "acceptance": plan.get("validation"),
            },
            next_actions=[
                f"Create {domain} adapter scaffold at runtime/connectors/{slug}_connector.py.",
                f"Expose {domain} connector endpoints under /api/runner/connectors/{slug}.",
                f"Map Brain evidence tables into {domain} source-count and provenance output.",
                f"Add tests for {domain} connector dashboard and validation contract.",
            ],
        )

    def _payload(self, executions: list[ConnectorExecution], source_plan_count: int) -> dict[str, Any]:
        serialized = [asdict(execution) for execution in executions]
        return {
            "build": "BUILD-019",
            "status": "connector_execution_scaffolds_ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_build": "BUILD-018",
            "source_plan_count": source_plan_count,
            "summary": {
                "executions": len(serialized),
                "critical": sum(1 for item in serialized if item.get("priority") == "CRITICAL"),
                "high": sum(1 for item in serialized if item.get("priority") == "HIGH"),
                "scaffold_ready": sum(1 for item in serialized if item.get("status") == "scaffold_ready"),
            },
            "executions": serialized,
            "next_actions": [action for item in serialized for action in item.get("scaffold", {}).get("next_actions", [])][:20],
        }

    def _persist(self, payload: dict[str, Any]) -> None:
        self.latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "connector"
