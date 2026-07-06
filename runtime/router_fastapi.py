"""FastAPI router for Calyx Runtime v0.1 and BUILD-047 science endpoints."""
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .config_loader import BrainConfigLoader
from .constitutional_orchestrator import orchestrator
from .infrastructure import InfrastructureRegistryService
from .scheduler import CalyxHeartbeat
from .science_registry import (
    AUDIT_ENDPOINT_TO_DEPARTMENT,
    audit_result,
    departments,
    mission_definitions,
    seed_missions,
    summary as science_summary,
)

# Keep one exported router because app.main imports only `router as runtime_router`.
# Routes are therefore declared with full API paths here.
router = APIRouter(tags=["Calyx Runtime"])


class ConstitutionalActionRequest(BaseModel):
    mission_id: str = Field(..., description="Mission id such as engineering, science, education, conservation, funding, community, or institutional_memory.")
    action: str = Field(..., description="Plain-language action Calyx wants to evaluate.")
    requested_autonomy_level: int = Field(0, ge=0, le=4)
    evidence: list[str] = Field(default_factory=list)
    reversible: bool = True
    provenance_available: bool = True


@router.get("/api/runtime/heartbeat")
def runtime_heartbeat():
    return CalyxHeartbeat().run_once()


@router.get("/api/runtime/health")
def runtime_health():
    return {"runtime": CalyxHeartbeat().run_once()}


@router.get("/api/runtime/constitutional/status")
def runtime_constitutional_status() -> dict[str, Any]:
    return orchestrator.status()


@router.get("/api/runtime/constitutional/policies")
def runtime_constitutional_policies() -> dict[str, Any]:
    return orchestrator.policy_registry()


@router.get("/api/runtime/constitutional/missions")
def runtime_constitutional_missions() -> dict[str, Any]:
    return orchestrator.mission_registry()


@router.get("/api/runtime/constitutional/decision-ledger")
def runtime_constitutional_decision_ledger() -> dict[str, Any]:
    return orchestrator.decision_ledger()


@router.get("/api/runtime/constitutional/governance-questions")
def runtime_constitutional_governance_questions() -> dict[str, Any]:
    return orchestrator.governance_questions()


@router.post("/api/runtime/constitutional/evaluate")
def runtime_constitutional_evaluate(request: ConstitutionalActionRequest) -> dict[str, Any]:
    return orchestrator.evaluate_action(
        mission_id=request.mission_id,
        action=request.action,
        requested_autonomy_level=request.requested_autonomy_level,
        evidence=request.evidence,
        reversible=request.reversible,
        provenance_available=request.provenance_available,
    )


@router.get("/api/science/departments", tags=["Orchid Continuum Science"])
def science_departments() -> dict[str, Any]:
    return {"departments": departments()}


@router.get("/api/science/missions", tags=["Orchid Continuum Science"])
def science_missions() -> dict[str, Any]:
    return {"missions": mission_definitions()}


@router.post("/api/science/seed-missions", tags=["Orchid Continuum Science"])
def science_seed_missions() -> dict[str, Any]:
    return seed_missions()


@router.get("/api/science/summary", tags=["Orchid Continuum Science"])
def science_summary_endpoint() -> dict[str, Any]:
    return science_summary()


@router.post("/api/science/audit/{audit_key}", tags=["Orchid Continuum Science"])
def science_audit(audit_key: str) -> dict[str, Any]:
    department_id = AUDIT_ENDPOINT_TO_DEPARTMENT.get(audit_key)
    if not department_id:
        return {
            "status": "unknown_audit_key",
            "audit_key": audit_key,
            "available_audits": sorted(AUDIT_ENDPOINT_TO_DEPARTMENT),
            "promoted_claims": False,
        }
    return audit_result(department_id)


@router.get("/api/config/manifest", tags=["Calyx Config"])
def config_manifest():
    return BrainConfigLoader().load_manifest()


@router.get("/api/config/runtime-services", tags=["Calyx Config"])
def config_runtime_services():
    return BrainConfigLoader().load_runtime_services()


@router.get("/api/config/governance-policy", tags=["Calyx Config"])
def config_governance_policy():
    return BrainConfigLoader().load_governance_policy()


@router.get("/api/config/knowledge-preservation-policy", tags=["Calyx Config"])
def config_knowledge_preservation_policy():
    return BrainConfigLoader().load_knowledge_preservation_policy()


@router.get("/api/infrastructure/registry", tags=["Calyx Infrastructure"])
def infrastructure_registry():
    return InfrastructureRegistryService().registry()


@router.get("/api/infrastructure/health", tags=["Calyx Infrastructure"])
def infrastructure_health():
    return InfrastructureRegistryService().health()
