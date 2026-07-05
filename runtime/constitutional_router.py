"""FastAPI router for BUILD-034 Constitutional Mission Orchestrator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .constitutional_orchestrator import orchestrator

router = APIRouter(prefix="/api/runner/constitutional", tags=["Calyx Constitutional Orchestrator"])


class ActionEvaluationRequest(BaseModel):
    mission_id: str = Field(..., description="Registered mission id, such as engineering, science, education, conservation, funding, community, or institutional_memory.")
    action: str = Field(..., description="Plain-language action Calyx wants to evaluate.")
    requested_autonomy_level: int = Field(0, ge=0, le=4)
    evidence: list[str] = Field(default_factory=list)
    reversible: bool = True
    provenance_available: bool = True


@router.get("/status")
def constitutional_status() -> dict[str, Any]:
    return orchestrator.status()


@router.get("/policies")
def constitutional_policies() -> dict[str, Any]:
    return orchestrator.policy_registry()


@router.get("/missions")
def constitutional_missions() -> dict[str, Any]:
    return orchestrator.mission_registry()


@router.get("/decision-ledger")
def constitutional_decision_ledger() -> dict[str, Any]:
    return orchestrator.decision_ledger()


@router.get("/governance-questions")
def constitutional_governance_questions() -> dict[str, Any]:
    return orchestrator.governance_questions()


@router.post("/evaluate")
def evaluate_constitutional_action(request: ActionEvaluationRequest) -> dict[str, Any]:
    return orchestrator.evaluate_action(
        mission_id=request.mission_id,
        action=request.action,
        requested_autonomy_level=request.requested_autonomy_level,
        evidence=request.evidence,
        reversible=request.reversible,
        provenance_available=request.provenance_available,
    )
