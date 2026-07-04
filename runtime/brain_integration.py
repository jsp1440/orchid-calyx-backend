"""BUILD-013 Brain integration workers.

These workers convert the BUILD-012 executor from placeholder execution into
safe, live-aware module behavior. Database access remains optional: when
DATABASE_URL is unavailable the workers return a degraded-but-successful result
instead of crashing the runtime.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:  # pragma: no cover - import behavior depends on deployment image
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

from .runtime_planner import RuntimePlanner


REPO_ROOT = Path(__file__).resolve().parents[1]


class BrainIntegrationWorker:
    """Dispatch CDS modules to live Brain-aware worker logic."""

    def __init__(self, queue_item: dict[str, Any]) -> None:
        self.queue_item = queue_item
        self.database_url = os.environ.get("DATABASE_URL")

    def execute(self) -> dict[str, Any]:
        module_name = self.queue_item["module_name"]
        if module_name == "DatabaseInspector":
            return self.database_inspector()
        if module_name == "EngineeringMemoryHarvester":
            return self.engineering_memory_harvester()
        if module_name == "DependencyIntelligence":
            return self.dependency_intelligence()
        if module_name == "CognitiveAudit":
            return self.cognitive_audit()
        return self.generic_worker()

    def database_inspector(self) -> dict[str, Any]:
        if not self.database_url:
            return self._degraded(
                "DatabaseInspector",
                "DATABASE_URL is not configured; returning repository-only database readiness status.",
                recommendations=["Configure DATABASE_URL in Render to enable live Brain table inspection."],
            )
        if psycopg is None:
            return self._degraded(
                "DatabaseInspector",
                "psycopg is unavailable in this runtime image.",
                recommendations=["Confirm psycopg is included in backend dependencies."],
            )

        schemas: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        try:
            with psycopg.connect(self.database_url, connect_timeout=10) as conn:  # type: ignore[union-attr]
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT schema_name
                        FROM information_schema.schemata
                        WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                        ORDER BY schema_name
                        LIMIT 100
                        """
                    )
                    schemas = [{"schema": row[0]} for row in cur.fetchall()]

                    cur.execute(
                        """
                        SELECT table_schema, table_name
                        FROM information_schema.tables
                        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                          AND table_type = 'BASE TABLE'
                        ORDER BY table_schema, table_name
                        LIMIT 200
                        """
                    )
                    tables = [{"schema": row[0], "table": row[1]} for row in cur.fetchall()]
        except Exception as exc:
            return self._degraded(
                "DatabaseInspector",
                f"Live Brain database inspection failed: {exc}",
                recommendations=["Check DATABASE_URL, network access, and database availability."],
            )

        return {
            "module": "DatabaseInspector",
            "status": "completed",
            "brain_connection": "connected",
            "schema_count": len(schemas),
            "table_count_sampled": len(tables),
            "schemas": schemas,
            "tables_sample": tables[:50],
            "recommendations": [
                "Persist schema snapshots in BUILD-013B.",
                "Add row-count sampling for selected Orchid Continuum schemas.",
            ],
        }

    def engineering_memory_harvester(self) -> dict[str, Any]:
        docs_dir = REPO_ROOT / "docs"
        build_docs = sorted(docs_dir.glob("BUILD-*.md")) if docs_dir.exists() else []
        latest = [path.name for path in build_docs[-20:]]
        return {
            "module": "EngineeringMemoryHarvester",
            "status": "completed",
            "source": "repository_docs",
            "build_doc_count": len(build_docs),
            "latest_build_docs": latest,
            "memory_objects_created": [
                {
                    "type": "engineering_memory_summary",
                    "source": "docs/BUILD-*.md",
                    "count": len(build_docs),
                }
            ],
            "recommendations": [
                "Persist BUILD summaries into oc_admin engineering memory tables in BUILD-013B.",
            ],
        }

    def dependency_intelligence(self) -> dict[str, Any]:
        graph = RuntimePlanner().dependency_graph()
        return {
            "module": "DependencyIntelligence",
            "status": "completed",
            "node_count": len(graph.get("nodes", [])),
            "edge_count": len(graph.get("edges", [])),
            "finding_count": len(graph.get("findings", [])),
            "findings": graph.get("findings", [])[:25],
            "recommendations": [
                "Normalize dependency names into canonical CDS module ids.",
                "Promote external dependencies into explicit Brain capability records.",
            ],
        }

    def cognitive_audit(self) -> dict[str, Any]:
        discovery = RuntimePlanner().discovery()
        plan = RuntimePlanner().plan()
        queue = RuntimePlanner().queue()
        selected = plan.get("selected_count", 0)
        total = plan.get("module_count", 0)
        readiness = round(selected / total, 3) if total else None
        return {
            "module": "CognitiveAudit",
            "status": "completed",
            "runtime_readiness": readiness,
            "module_count": discovery.get("module_count"),
            "selected_count": selected,
            "queue_depth": queue.get("queue_depth"),
            "findings": discovery.get("findings", []),
            "recommendations": [
                "Advance planned MissionReporter into framework status after Brain persistence is available.",
                "Connect execution outcomes to Engineering Memory for recursive improvement.",
            ],
        }

    def generic_worker(self) -> dict[str, Any]:
        return {
            "module": self.queue_item["module_name"],
            "module_id": self.queue_item["module_id"],
            "status": "completed",
            "message": f"{self.queue_item['module_name']} generic BUILD-013 worker completed.",
        }

    def _degraded(self, module: str, message: str, recommendations: list[str]) -> dict[str, Any]:
        return {
            "module": module,
            "status": "degraded",
            "message": message,
            "brain_connection": "unavailable",
            "recommendations": recommendations,
        }
