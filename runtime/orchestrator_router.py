"""FastAPI endpoints for BUILD-044 Calyx Autonomous Orchestrator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from .autonomous_orchestrator import CalyxAutonomousOrchestrator, OrchestratorConfigError
from .constitutional_orchestrator import AutonomyLevel, orchestrator as constitutional_orchestrator


router = APIRouter(prefix="/api/orchestrator", tags=["Calyx Autonomous Orchestrator"])
AUTH_REQUIRED = [Depends(verify_owner_or_api_key)]


class CreateTaskRequest(BaseModel):
    task_type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


def orchestrator() -> CalyxAutonomousOrchestrator:
    return CalyxAutonomousOrchestrator()


def handle_config_error(exc: OrchestratorConfigError) -> None:
    raise HTTPException(status_code=503, detail=str(exc)) from exc


def action_contract() -> dict[str, dict[str, Any]]:
    def requires_auth(reason: str, *, risk: str = "medium") -> dict[str, Any]:
        return {
            "allowed": False,
            "state": "requires_owner_authorization",
            "auth": "owner_session_or_api_key_required",
            "risk": risk,
            "reason": reason,
        }

    return {
        "seed": requires_auth("Seeds durable agents and tasks in the orchestrator database."),
        "createTask": requires_auth("Creates a durable orchestrator task."),
        "approveTask": requires_auth("Approves a queued task for autonomous execution.", risk="high"),
        "runOnce": requires_auth("Executes one orchestrator loop against durable task state.", risk="high"),
    }


def evaluate_orchestrator_action(
    action: str,
    *,
    requested_autonomy_level: int = int(AutonomyLevel.SAFE_OPERATIONS),
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return constitutional_orchestrator.evaluate_action(
        mission_id="engineering",
        action=f"orchestrator:{action}",
        requested_autonomy_level=requested_autonomy_level,
        evidence=evidence or [f"route=/api/orchestrator/{action}"],
        reversible=True,
        provenance_available=True,
    )


@router.post("/seed", dependencies=AUTH_REQUIRED)
def seed_orchestrator():
    decision = evaluate_orchestrator_action("seed", evidence=["authenticated API request", "idempotent seed"])
    try:
        return {**orchestrator().seed_defaults(), "decision": decision["decision"], "allowedActions": action_contract()}
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.get("/agents")
def list_agents():
    try:
        return {**orchestrator().list_agents(), "allowedActions": action_contract()}
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.get("/tasks")
def list_tasks(limit: int = Query(default=100, ge=1, le=500)):
    try:
        return {**orchestrator().list_tasks(limit=limit), "allowedActions": action_contract()}
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.post("/tasks", dependencies=AUTH_REQUIRED)
def create_task(request: CreateTaskRequest):
    decision = evaluate_orchestrator_action(
        "create_task",
        evidence=["authenticated API request", f"task_type={request.task_type}"],
    )
    try:
        return {
            **orchestrator().create_task(
            task_type=request.task_type,
            title=request.title,
            payload=request.payload,
            priority=request.priority,
            ),
            "decision": decision["decision"],
            "allowedActions": action_contract(),
        }
    except OrchestratorConfigError as exc:
        handle_config_error(exc)


@router.post("/tasks/{task_id}/approve", dependencies=AUTH_REQUIRED)
def approve_task(task_id: int):
    decision = evaluate_orchestrator_action(
        "approve_task",
        requested_autonomy_level=int(AutonomyLevel.OWNER_APPROVAL_REQUIRED),
        evidence=["authenticated API request", f"task_id={task_id}"],
    )
    if decision["decision"]["status"] == "review_required":
        return {"status": "review_required", "decision": decision["decision"], "allowedActions": action_contract()}

    try:
        result = orchestrator().approve_task(task_id)
    except OrchestratorConfigError as exc:
        handle_config_error(exc)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result)
    return {**result, "decision": decision["decision"], "allowedActions": action_contract()}


@router.post("/run-once", dependencies=AUTH_REQUIRED)
def run_once():
    decision = evaluate_orchestrator_action(
        "run_once",
        requested_autonomy_level=int(AutonomyLevel.OWNER_APPROVAL_REQUIRED),
        evidence=["authenticated API request", "orchestrator loop requested"],
    )
    if decision["decision"]["status"] == "review_required":
        return {"status": "review_required", "decision": decision["decision"], "allowedActions": action_contract()}

    try:
        return {**orchestrator().run_once(), "decision": decision["decision"], "allowedActions": action_contract()}
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
        return {**orchestrator().health(), "allowedActions": action_contract()}
    except OrchestratorConfigError as exc:
        handle_config_error(exc)
