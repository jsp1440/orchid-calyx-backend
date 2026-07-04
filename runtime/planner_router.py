"""FastAPI endpoints for BUILD-012C runtime planning and BUILD-012D execution."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .cds_loader import CDSRegistryError, clear_cds_cache
from .runtime_executor import RuntimeExecutor
from .runtime_planner import RuntimePlanner


router = APIRouter(prefix="/api/runner", tags=["Calyx Runtime Planner"])


def planner() -> RuntimePlanner:
    return RuntimePlanner()


def executor() -> RuntimeExecutor:
    return RuntimeExecutor()


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
