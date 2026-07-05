"""FastAPI router for Calyx Runtime v0.1."""
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .config_loader import BrainConfigLoader
from .constitutional_orchestrator import orchestrator
from .infrastructure import InfrastructureRegistryService
from .scheduler import CalyxHeartbeat

router = APIRouter(prefix="/api/runtime", tags=["Calyx Runtime"])
config_router = APIRouter(prefix="/api/config", tags=["Calyx Config"])
infrastructure_router = APIRouter(prefix="/api/infrastructure", tags=["Calyx Infrastructure"])


class ConstitutionalActionRequest(BaseModel):
    mission_id: str = Field(..., description="Mission id such as engineering, science, education, conservation, funding, community, or institutional_memory.")
    action: str = Field(..., description="Plain-language action Calyx wants to evaluate.")
    requested_autonomy_level: int = Field(0, ge=0, le=4)
    evidence: list[str] = Field(default_factory=list)
    reversible: bool = True
    provenance_available: bool = True


@router.get("/heartbeat")
def runtime_heartbeat():
    return CalyxHeartbeat().run_once()


@router.get("/health")
def runtime_health():
    return {"runtime": CalyxHeartbeat().run_once()}


@router.get("/constitutional/status")
def runtime_constitutional_status() -> dict[str, Any]:
    return orchestrator.status()


@router.get("/constitutional/policies")
def runtime_constitutional_policies() -> dict[str, Any]:
    return orchestrator.policy_registry()


@router.get("/constitutional/missions")
def runtime_constitutional_missions() -> dict[str, Any]:
    return orchestrator.mission_registry()


@router.get("/constitutional/decision-ledger")
def runtime_constitutional_decision_ledger() -> dict[str, Any]:
    return orchestrator.decision_ledger()


@router.get("/constitutional/governance-questions")
def runtime_constitutional_governance_questions() -> dict[str, Any]:
    return orchestrator.governance_questions()


@router.post("/constitutional/evaluate")
def runtime_constitutional_evaluate(request: ConstitutionalActionRequest) -> dict[str, Any]:
    return orchestrator.evaluate_action(
        mission_id=request.mission_id,
        action=request.action,
        requested_autonomy_level=request.requested_autonomy_level,
        evidence=request.evidence,
        reversible=request.reversible,
        provenance_available=request.provenance_available,
    )


@config_router.get("/manifest")
def config_manifest():
    return BrainConfigLoader().load_manifest()


@config_router.get("/runtime-services")
def config_runtime_services():
    return BrainConfigLoader().load_runtime_services()


@config_router.get("/governance-policy")
def config_governance_policy():
    return BrainConfigLoader().load_governance_policy()


@config_router.get("/knowledge-preservation-policy")
def config_knowledge_preservation_policy():
    return BrainConfigLoader().load_knowledge_preservation_policy()


@infrastructure_router.get("/registry")
def infrastructure_registry():
    return InfrastructureRegistryService().registry()


@infrastructure_router.get("/health")
def infrastructure_health():
    return InfrastructureRegistryService().health()
