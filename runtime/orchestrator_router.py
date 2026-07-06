"""FastAPI endpoints for BUILD-044 Calyx Autonomous Orchestrator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .autonomous_orchestrator import CalyxAutonomousOrchestrator, OrchestratorConfigError


router = APIRouter(prefix="/api/orchestrator", tags=["Calyx Autonomous Orchestrator"])


class CreateTaskRequest(BaseModel):
    task_type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


def orchestrator() -> CalyxAutonomousOrchestrator:
    return CalyxAutonomousOrchestrator()


def handle_config_error(exc: OrchestratorConfigError) -> None:
    raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/seed")
def seed_orchestrator():
    try:
        return orchestrator().seed_defaults()
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.get("/agents")
def list_agents():
    try:
        return orchestrator().list_agents()
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.get("/tasks")
def list_tasks(limit: int = Query(default=100, ge=1, le=500)):
    try:
        return orchestrator().list_tasks(limit=limit)
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.post("/tasks")
def create_task(request: CreateTaskRequest):
    try:
        return orchestrator().create_task(
            task_type=request.task_type,
            title=request.title,
            payload=request.payload,
            priority=request.priority,
        )
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.post("/tasks/{task_id}/approve")
def approve_task(task_id: int):
    try:
        result = orchestrator().approve_task(task_id)
    except OrchestratorConfigError as exc:
        handle_config_error(exc)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return result


@router.post("/run-once")
def run_once():
    try:
        return orchestrator().run_once()
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.get("/observations")
def observations(limit: int = Query(default=100, ge=1, le=500)):
    try:
        return orchestrator().observations(limit=limit)
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.get("/runs")
def runs(limit: int = Query(default=50, ge=1, le=500)):
    try:
        return orchestrator().runs(limit=limit)
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.get("/health")
def health():
    try:
        return orchestrator().health()
    except OrchestratorConfigError as exc:
        handle_config_error(exc)
