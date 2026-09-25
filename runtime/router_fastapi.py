"""FastAPI router for Calyx Runtime v0.1, constitutional guardrails, and BUILD-049 audit commands."""
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from .config_loader import BrainConfigLoader
from .constitutional_orchestrator import orchestrator
from .featured_genus_sentinel import FeaturedGenusSentinel
from .infrastructure import InfrastructureRegistryService
from .scheduler import CalyxHeartbeat
from .science_registry import (
    AUDIT_ENDPOINT_TO_DEPARTMENT,
    audit_result,
    coverage_gaps,
    datasets,
    department_by_id,
    departments,
    dossier_queue,
    harvester_status,
    integration_status,
    mission_definitions,
    seed_missions,
    summary as science_summary,
)

router = APIRouter(prefix="/api/runtime", tags=["Calyx Runtime"])
config_router = APIRouter(prefix="/api/config", tags=["Calyx Config"])
infrastructure_router = APIRouter(prefix="/api/infrastructure", tags=["Calyx Infrastructure"])
science_router = APIRouter(prefix="/api/science", tags=["Orchid Continuum Science"])


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


@router.get("/featured-genus/audit")
def audit_featured_genus_media() -> dict[str, Any]:
    """Run the binding Featured Genus audit gate.

    This audit is intentionally read-only. It returns promotion_allowed=false
    until the BUILD-208 source contract and a live browser-render probe are
    evidenced. It is the command Calyx must consult before recommending any
    Featured Genus media merge or deployment.
    """
    return FeaturedGenusSentinel().audit()


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


@router.post("/constitutional/evaluate", dependencies=[Depends(verify_owner_or_api_key)])
def runtime_constitutional_evaluate(request: ConstitutionalActionRequest) -> dict[str, Any]:
    return orchestrator.evaluate_action(
        mission_id=request.mission_id,
        action=request.action,
        requested_autonomy_level=request.requested_autonomy_level,
        evidence=request.evidence,
        reversible=request.reversible,
        provenance_available=request.provenance_available,
    )


@science_router.get("/departments")
def science_departments() -> dict[str, Any]:
    return {"departments": departments()}


@science_router.get("/departments/{department_id}")
def science_department_detail(department_id: str) -> dict[str, Any]:
    try:
        return {"department": department_by_id(department_id)}
    except KeyError:
        return {"status": "unknown_department", "department_id": department_id}


@science_router.get("/missions")
def science_missions() -> dict[str, Any]:
    return {"missions": mission_definitions()}


@science_router.post("/seed-missions", dependencies=[Depends(verify_owner_or_api_key)])
def science_seed_missions() -> dict[str, Any]:
    return seed_missions()


@science_router.get("/summary")
def science_summary_endpoint() -> dict[str, Any]:
    return science_summary()


@science_router.get("/status")
def science_status_endpoint() -> dict[str, Any]:
    return integration_status()


@science_router.get("/datasets")
def science_datasets_endpoint() -> dict[str, Any]:
    return datasets()


@science_router.get("/gaps")
def science_gaps_endpoint() -> dict[str, Any]:
    return coverage_gaps()


@science_router.get("/harvesters")
def science_harvesters_endpoint() -> dict[str, Any]:
    return harvester_status()


@science_router.get("/dossiers")
def science_dossiers_endpoint() -> dict[str, Any]:
    return dossier_queue()


@science_router.post("/audit/{audit_key}", dependencies=[Depends(verify_owner_or_api_key)])
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


def serve_brain_record(path: str, loader: BrainConfigLoader | None = None):
    """Serve one Brain record under the Brain's unavailable contract.

    Reachable: the record plus ``config_source.status == "loaded"``. Unreachable
    after a good load: the last-known record plus ``status == "unavailable"``,
    ``last_known_at``, ``last_known_sha256`` and the error text, still 200.
    Unreachable and never loaded in this process: 503 with ``last_known_at``
    ``None`` and the reason. A record is never fabricated and an outage is never
    a 500. Contract: Orchid-Continuum-Brain
    ``contracts/federation_records_v1.json#unavailable_contract``.
    """
    result = (loader or BrainConfigLoader()).load_with_source(path)
    if result.record is None:
        source = result.config_source
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "repo": source["repo"],
                "ref": source["ref"],
                "path": path,
                "last_known_at": None,
                "last_known_sha256": None,
                "reason": source.get("error"),
            },
        )
    return {**result.record, "config_source": result.config_source}


@config_router.get("/brain-source")
def config_brain_source():
    """Which Brain ref this runtime reads, and whether it is the served one.

    ``stale`` is true whenever the pinned ref is not the Brain's served ref
    (``main``). Resolution of the pinned ref's commit and date is one bounded
    call; if it fails, ``resolution`` says so and ``stale`` is unaffected.
    """
    return BrainConfigLoader().describe_ref(resolve=True)


@config_router.get("/manifest")
def config_manifest():
    return serve_brain_record("config/calyx_core_manifest.json")


@config_router.get("/runtime-services")
def config_runtime_services():
    return serve_brain_record("config/runtime_services.json")


@config_router.get("/governance-policy")
def config_governance_policy():
    return serve_brain_record("config/governance_policy.json")


@config_router.get("/knowledge-preservation-policy")
def config_knowledge_preservation_policy():
    return serve_brain_record("config/knowledge_preservation_policy.json")


@infrastructure_router.get("/registry")
def infrastructure_registry():
    return InfrastructureRegistryService().registry()


@infrastructure_router.get("/health")
def infrastructure_health():
    return InfrastructureRegistryService().health()


router.include_router(science_router)
