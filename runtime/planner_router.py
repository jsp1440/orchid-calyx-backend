"""FastAPI endpoints for runtime planning, execution, Brain integration, and autonomous discovery."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .autonomous_discovery import AutonomousDiscoveryEngine
from .brain_integration import BrainIntegrationWorker
from .cds_loader import CDSRegistryError, clear_cds_cache
from .runtime_executor import RuntimeExecutor
from .runtime_planner import RuntimePlanner


router = APIRouter(prefix="/api/runner", tags=["Calyx Runtime Planner"])


def planner() -> RuntimePlanner:
    return RuntimePlanner()


def executor() -> RuntimeExecutor:
    return RuntimeExecutor()


def discovery_engine() -> AutonomousDiscoveryEngine:
    return AutonomousDiscoveryEngine()


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
