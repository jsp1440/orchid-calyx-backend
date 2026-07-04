"""BUILD-012C runtime planner.

The planner consumes the CDS registry introduced in BUILD-012B and produces
an explicit discovery report, dependency graph, execution plan, and runtime
queue. It is intentionally file-backed and deterministic so it can run in
Render without a database connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cds_loader import get_cds_loader


STATUS_WEIGHT = {
    "live-ready": 100,
    "framework": 70,
    "prototype": 60,
    "planned": 30,
}

DOMAIN_WEIGHT = {
    "Engineering": 100,
    "Mission Control": 90,
    "Cognitive": 85,
    "Scientific": 80,
    "Exploration": 60,
    "Narrative": 50,
}


@dataclass(frozen=True)
class PlannerFinding:
    severity: str
    code: str
    message: str
    module_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "module_id": self.module_id,
        }


class RuntimePlanner:
    """Build runtime plans from the live CDS registry."""

    def __init__(self) -> None:
        self.cds = get_cds_loader()

    def discovery(self) -> dict[str, Any]:
        modules = self.cds.modules()
        findings = self._validate_modules(modules)
        return {
            "build": "BUILD-012C",
            "status": "ok" if not findings else "needs_attention",
            "module_count": len(modules),
            "modules": [self._module_summary(module) for module in modules],
            "findings": [finding.to_dict() for finding in findings],
        }

    def dependency_graph(self) -> dict[str, Any]:
        modules = self.cds.modules()
        module_ids = {module["module_id"] for module in modules}
        nodes = []
        edges = []
        findings: list[PlannerFinding] = []

        for module in modules:
            nodes.append(
                {
                    "module_id": module["module_id"],
                    "name": module["name"],
                    "domain": module["domain"],
                    "status": module["status"],
                }
            )
            for dependency in module.get("dependencies", []):
                dependency_key = self._dependency_to_module_id(dependency, modules)
                if dependency_key and dependency_key in module_ids:
                    edges.append(
                        {
                            "from": dependency_key,
                            "to": module["module_id"],
                            "label": dependency,
                        }
                    )
                elif dependency:
                    findings.append(
                        PlannerFinding(
                            severity="info",
                            code="external_dependency",
                            message=f"Dependency is external or not yet registered: {dependency}",
                            module_id=module["module_id"],
                        )
                    )

        return {
            "build": "BUILD-012C",
            "nodes": nodes,
            "edges": edges,
            "findings": [finding.to_dict() for finding in findings],
        }

    def plan(self) -> dict[str, Any]:
        modules = self.cds.modules()
        priorities = self.cds.priorities()
        priority_text = [item["priority"] for item in priorities]
        planned_modules = []

        for module in modules:
            score = self._score_module(module, priority_text)
            planned_modules.append(
                {
                    **self._module_summary(module),
                    "priority_score": score,
                    "selected": self._is_selectable(module),
                    "skip_reason": None if self._is_selectable(module) else self._skip_reason(module),
                    "planned_action": module.get("next_action"),
                }
            )

        planned_modules.sort(key=lambda module: module["priority_score"], reverse=True)
        for index, module in enumerate(planned_modules, start=1):
            module["plan_rank"] = index

        return {
            "build": "BUILD-012C",
            "status": "planned",
            "module_count": len(planned_modules),
            "selected_count": len([module for module in planned_modules if module["selected"]]),
            "plan": planned_modules,
        }

    def queue(self) -> dict[str, Any]:
        plan = self.plan()["plan"]
        queue_items = []
        skipped = []

        for module in plan:
            if module["selected"]:
                queue_items.append(
                    {
                        "queue_rank": len(queue_items) + 1,
                        "job_name": f"cds:{module['module_id']}",
                        "module_id": module["module_id"],
                        "module_name": module["name"],
                        "priority_score": module["priority_score"],
                        "action": module.get("planned_action"),
                    }
                )
            else:
                skipped.append(
                    {
                        "module_id": module["module_id"],
                        "module_name": module["name"],
                        "reason": module["skip_reason"],
                    }
                )

        return {
            "build": "BUILD-012C",
            "status": "ready",
            "queue_depth": len(queue_items),
            "queue": queue_items,
            "skipped": skipped,
        }

    def _validate_modules(self, modules: list[dict[str, Any]]) -> list[PlannerFinding]:
        findings: list[PlannerFinding] = []
        seen: set[str] = set()
        for module in modules:
            module_id = module.get("module_id")
            if module_id in seen:
                findings.append(
                    PlannerFinding(
                        severity="error",
                        code="duplicate_module_id",
                        message=f"Duplicate CDS module id: {module_id}",
                        module_id=module_id,
                    )
                )
            seen.add(module_id)
            if not module.get("next_action"):
                findings.append(
                    PlannerFinding(
                        severity="warning",
                        code="missing_next_action",
                        message="Module has no next action for the planner.",
                        module_id=module_id,
                    )
                )
        return findings

    def _module_summary(self, module: dict[str, Any]) -> dict[str, Any]:
        return {
            "module_id": module["module_id"],
            "name": module["name"],
            "domain": module["domain"],
            "status": module["status"],
            "runtime_state": module.get("runtime_state", {}),
            "dependencies": module.get("dependencies", []),
        }

    def _score_module(self, module: dict[str, Any], priority_text: list[str]) -> int:
        score = STATUS_WEIGHT.get(module.get("status"), 10)
        score += DOMAIN_WEIGHT.get(module.get("domain"), 10)
        joined = " ".join(priority_text).lower()
        name = module.get("name", "").lower()
        module_id = module.get("module_id", "").lower()
        if name and name in joined:
            score += 80
        if module_id and module_id in joined:
            score += 40
        if module.get("next_action"):
            score += 10
        return score

    def _is_selectable(self, module: dict[str, Any]) -> bool:
        return module.get("status") in {"live-ready", "framework", "prototype"}

    def _skip_reason(self, module: dict[str, Any]) -> str:
        if module.get("status") == "planned":
            return "module is still planned"
        return f"module status is not executable: {module.get('status')}"

    def _dependency_to_module_id(self, dependency: str, modules: list[dict[str, Any]]) -> str | None:
        normalized = dependency.lower().strip()
        for module in modules:
            if normalized in {module["module_id"].lower(), module["name"].lower()}:
                return module["module_id"]
        return None
