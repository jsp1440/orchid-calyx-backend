"""FastAPI endpoints for runtime planning, execution, Brain integration, autonomous discovery, discovery snapshots, knowledge gaps, diagnostics, connector planning, and connector execution framework.

BUILD-020: Includes the new generic Connector Execution Framework endpoints at /api/connectors
BUILD-019: Maintains backward compatibility with connector scaffold endpoints at /api/runner/connector-scaffolds
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .autonomous_discovery import AutonomousDiscoveryEngine
from .brain_integration import BrainIntegrationWorker
from .cds_loader import CDSRegistryError, clear_cds_cache
from .connector_planner import BrainConnectorPlanner
from .connector_runtime import ConnectorRuntimeBuilder
from .connector_routes import router as connector_router
from .discovery_memory import DiscoveryMemoryStore
from .knowledge_gap_diagnostics import KnowledgeGapDiagnosticsEngine
from .knowledge_gap_discovery import KnowledgeGapDiscoveryEngine
from .runtime_executor import RuntimeExecutor
from .runtime_planner import RuntimePlanner


router = APIRouter(prefix="/api/runner", tags=["Calyx Runtime Planner"])

# Include BUILD-020 connector execution framework routes
# These are at /api/connectors (not /api/runner/connectors)
# This is done in the main app initialization


def planner() -> RuntimePlanner:
    return RuntimePlanner()


def executor() -> RuntimeExecutor:
    return RuntimeExecutor()


def discovery_engine() -> AutonomousDiscoveryEngine:
    return AutonomousDiscoveryEngine()


def snapshot_store() -> DiscoveryMemoryStore:
    return DiscoveryMemoryStore()


def gap_engine() -> KnowledgeGapDiscoveryEngine:
    return KnowledgeGapDiscoveryEngine()


def diagnostic_engine() -> KnowledgeGapDiagnosticsEngine:
    return KnowledgeGapDiagnosticsEngine()


def connector_planner() -> BrainConnectorPlanner:
    return BrainConnectorPlanner()


def connector_runtime() -> ConnectorRuntimeBuilder:
    return ConnectorRuntimeBuilder()


def brain_worker(module_id: str, module_name: str, action: str) -> BrainIntegrationWorker:
    return BrainIntegrationWorker(
        {
            "module_id": module_id,
            "module_name": module_name,
            "job_name": f"cds:{module_id}",
            "action": action,
        }
    )


@router.get("/discovery")
def runner_discovery():
    try:
        return planner().discovery()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dependencies")
def runner_dependencies():
    try:
        return planner().dependency_graph()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/plan")
def runner_plan():
    try:
        return planner().plan()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/queue")
def runner_queue():
    try:
        return planner().queue()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild-plan")
def runner_rebuild_plan():
    try:
        clear_cds_cache()
        return {
            "status": "rebuilt",
            "discovery": planner().discovery(),
            "plan": planner().plan(),
            "queue": planner().queue(),
        }
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/execute")
def execute_queue(limit: int | None = Query(default=None, ge=1, le=100)):
    return executor().execute_queue(limit=limit)


@router.post("/execute/{module_id}")
def execute_module(module_id: str):
    result = executor().execute_module(module_id)
    if result.get("status") == "not_found_or_not_selectable":
        raise HTTPException(status_code=404, detail=result)
    return result


@router.get("/executions")
def list_executions(limit: int = Query(default=50, ge=1, le=500)):
    return executor().list_executions(limit=limit)


@router.get("/executions/{execution_id}")
def get_execution(execution_id: str):
    record = executor().get_execution(execution_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Execution not found: {execution_id}")
    return record


@router.get("/history")
def execution_history():
    return executor().history()


@router.get("/events")
def execution_events(limit: int = Query(default=100, ge=1, le=500)):
    return executor().events(limit=limit)


@router.post("/retry/{execution_id}")
def retry_execution(execution_id: str):
    result = executor().retry(execution_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return result


@router.post("/cancel/{execution_id}")
def cancel_execution(execution_id: str):
    result = executor().cancel(execution_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return result


@router.get("/brain-summary")
def brain_summary():
    queue = planner().queue()
    return {
        "build": "BUILD-013",
        "status": "brain_integration_available",
        "queue_depth": queue.get("queue_depth"),
        "first_live_modules": [
            "DatabaseInspector",
            "EngineeringMemoryHarvester",
            "DependencyIntelligence",
            "CognitiveAudit",
        ],
    }


@router.get("/brain-status")
def brain_status():
    return brain_worker("CDS-ENG-002", "DatabaseInspector", "Inspect live Brain database state").database_inspector()


@router.get("/engineering-memory")
def engineering_memory_status():
    return brain_worker("CDS-ENG-001", "EngineeringMemoryHarvester", "Harvest BUILD reports").engineering_memory_harvester()


@router.get("/dependency-intelligence")
def dependency_intelligence_status():
    return brain_worker("CDS-SCI-001", "DependencyIntelligence", "Inspect dependency graph").dependency_intelligence()


@router.get("/cognitive-audit")
def cognitive_audit_status():
    return brain_worker("CDS-COG-001", "CognitiveAudit", "Audit runtime readiness").cognitive_audit()


@router.get("/discover")
def get_autonomous_discovery():
    return discovery_engine().cached_or_discover()


@router.post("/discover")
def run_autonomous_discovery():
    return discovery_engine().discover(write_cache=True)


@router.get("/modules")
def discovered_modules():
    return discovery_engine().modules()


@router.get("/capabilities")
def discovered_capabilities():
    return discovery_engine().capabilities()


@router.get("/graph")
def discovered_graph():
    return discovery_engine().graph()


@router.get("/recommendations")
def discovered_recommendations():
    return discovery_engine().recommendations()


@router.get("/schedule")
def discovered_schedule():
    return discovery_engine().schedule()


@router.get("/discovery-dashboard")
def discovery_dashboard():
    payload = discovery_engine().cached_or_discover()
    return {"build": "BUILD-014", "dashboard": payload.get("summary", {}), "recommendations": payload.get("recommendations", [])[:5]}


@router.post("/rebuild")
def rebuild_discovery():
    return discovery_engine().discover(write_cache=True)


@router.post("/discovery-snapshots/capture")
def capture_discovery_snapshot():
    return snapshot_store().capture()


@router.get("/discovery-snapshots/latest")
def latest_discovery_snapshot():
    return snapshot_store().latest()


@router.get("/discovery-snapshots")
def list_discovery_snapshots(limit: int = Query(default=20, ge=1, le=100)):
    return snapshot_store().list_snapshots(limit=limit)


@router.get("/discovery-snapshots/diff")
def diff_discovery_snapshots():
    return snapshot_store().diff_latest()


@router.get("/discovery-snapshots/timeline")
def discovery_snapshot_timeline(limit: int = Query(default=20, ge=1, le=100)):
    return snapshot_store().timeline(limit=limit)


@router.get("/discovery-snapshots/health")
def discovery_snapshot_health():
    return snapshot_store().health()


@router.get("/knowledge-gaps")
def knowledge_gaps():
    return gap_engine().gaps()


@router.post("/knowledge-gaps/discover")
def discover_knowledge_gaps():
    return gap_engine().discover(write_cache=True)


@router.get("/knowledge-gaps/latest")
def latest_knowledge_gaps():
    return gap_engine().latest()


@router.get("/knowledge-gaps/domains")
def knowledge_gap_domains():
    return gap_engine().domains()


@router.get("/knowledge-gaps/priorities")
def knowledge_gap_priorities():
    return gap_engine().priorities()


@router.get("/knowledge-gaps/queue")
def knowledge_gap_queue(limit: int = Query(default=10, ge=1, le=50)):
    return gap_engine().research_queue(limit=limit)


@router.get("/knowledge-gaps/dashboard")
def knowledge_gap_dashboard():
    return gap_engine().dashboard()


@router.post("/knowledge-diagnostics/discover")
def discover_knowledge_diagnostics():
    return diagnostic_engine().diagnose(write_cache=True)


@router.get("/knowledge-diagnostics/latest")
def latest_knowledge_diagnostics():
    return diagnostic_engine().latest()


@router.get("/knowledge-diagnostics/domains")
def knowledge_diagnostic_domains():
    return diagnostic_engine().domains()


@router.get("/knowledge-diagnostics/gaps")
def knowledge_diagnostic_gaps():
    return diagnostic_engine().gaps()


@router.get("/knowledge-diagnostics/queue")
def knowledge_diagnostic_queue(limit: int = Query(default=10, ge=1, le=50)):
    return diagnostic_engine().queue(limit=limit)


@router.get("/knowledge-diagnostics/dashboard")
def knowledge_diagnostic_dashboard():
    return diagnostic_engine().dashboard()


@router.get("/connector-plans")
def get_connector_plans():
    return connector_planner().latest()


@router.post("/connector-plans/generate")
def generate_connector_plans():
    return connector_planner().generate(write_cache=True)


@router.get("/connector-plans/domains")
def connector_plan_domains():
    return connector_planner().domains()


@router.get("/connector-plans/queue")
def connector_plan_queue(limit: int = Query(default=10, ge=1, le=50)):
    return connector_planner().queue(limit=limit)


@router.get("/connector-plans/dashboard")
def connector_plan_dashboard():
    return connector_planner().dashboard()


@router.post("/connector-scaffolds/build")
def build_connector_scaffolds(limit: int | None = Query(default=None, ge=1, le=50)):
    return connector_runtime().build_queue(limit=limit, write_cache=True)


@router.post("/connector-scaffolds/build/{plan_id}")
def build_connector_scaffold(plan_id: str):
    result = connector_runtime().build_plan(plan_id, write_cache=True)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return result


@router.get("/connector-scaffolds")
def connector_scaffolds():
    return connector_runtime().latest()


@router.get("/connector-scaffolds/runs")
def connector_scaffold_runs(limit: int = Query(default=20, ge=1, le=100)):
    return connector_runtime().runs(limit=limit)


@router.get("/connector-scaffolds/runs/{run_id}")
def connector_scaffold_run(run_id: str):
    result = connector_runtime().get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Connector scaffold run not found: {run_id}")
    return result


@router.get("/connector-scaffolds/queue")
def connector_scaffold_queue(limit: int = Query(default=10, ge=1, le=50)):
    return connector_runtime().queue(limit=limit)


@router.get("/connector-scaffolds/dashboard")
def connector_scaffold_dashboard():
    return connector_runtime().dashboard()


@router.get("/connectors/{slug}")
def connector_runtime_endpoint(slug: str):
    expected_prefix = f"/api/runner/connectors/{slug}"
    for row in connector_runtime().latest().get("runs", []):
        if row.get("scaffold", {}).get("endpoint_prefix") == expected_prefix:
            return {"build": "BUILD-019", "status": "connector_scaffold_available", "connector": row}
    raise HTTPException(status_code=404, detail=f"Connector scaffold not found: {slug}")


@router.get("/connectors/{slug}/dashboard")
def connector_runtime_dashboard(slug: str):
    payload = connector_runtime_endpoint(slug)
    connector = payload.get("connector", {})
    scaffold = connector.get("scaffold", {})
    return {
        "build": "BUILD-019",
        "status": payload.get("status"),
        "domain": connector.get("domain"),
        "priority": connector.get("priority"),
        "adapter_name": scaffold.get("adapter_name"),
        "module_path": scaffold.get("module_path"),
        "connector_targets": scaffold.get("connector_targets", []),
        "validation_contract": scaffold.get("validation_contract", {}),
        "next_actions": scaffold.get("next_actions", []),
    }
