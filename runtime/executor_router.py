"""FastAPI endpoints for BUILD-012D runtime execution."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import verify_api_key
from .runtime_executor import RuntimeExecutor


router = APIRouter(prefix="/api/runner", tags=["Calyx Runtime Executor"])
WRITE_AUTH = [Depends(verify_api_key)]


def executor() -> RuntimeExecutor:
    return RuntimeExecutor()


@router.post("/execute", dependencies=WRITE_AUTH)
def execute_queue(limit: int | None = Query(default=None, ge=1, le=100)):
    return executor().execute_queue(limit=limit)


@router.post("/execute/{module_id}", dependencies=WRITE_AUTH)
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


@router.post("/retry/{execution_id}", dependencies=WRITE_AUTH)
def retry_execution(execution_id: str):
    result = executor().retry(execution_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return result


@router.post("/cancel/{execution_id}", dependencies=WRITE_AUTH)
def cancel_execution(execution_id: str):
    result = executor().cancel(execution_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return result
