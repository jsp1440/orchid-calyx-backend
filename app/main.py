from fastapi import Depends, FastAPI
from pydantic import BaseModel
from typing import Optional, Any
import os
import re
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from app.routers import (
    awards,
    calyx_core,
    entries,
    feedback,
    harvesters,
    health,
    judging,
    reference_docs,
)
from app.intake.routes import router as intake_router
from app.semantic.routers import router as semantic_router
from app.source_registry.routes import router as source_registry_router
from app.document_import.routes import router as document_import_router
from app.document_intelligence.routes import router as document_intelligence_router
from app.semantic_index.routes import router as semantic_index_router
from app.evidence_retrieval.routes import router as evidence_retrieval_router
from app.candidate_knowledge.routes import router as candidate_knowledge_router
from app.evidence_aggregation.routes import router as evidence_aggregation_router
from app.design_intelligence.routes import router as design_intelligence_router
from app.design_planning.routes import router as design_planning_router
from app.implementation_planning.routes import router as implementation_planning_router
from app.scientific_interpretation.routes import router as scientific_interpretation_router
from app.ontology.routers import router as ontology_router
from app.concepts.routers import router as concepts_router
from app.brain.routes import router as brain_router
from app.literature_extraction.routes import router as literature_extraction_router
from app.publication.routers import router as publication_router
from app.research_workspace.routes import router as research_workspace_router
from app.reasoning_ledger.routes import (
    project_router as reasoning_ledger_project_router,
    router as reasoning_ledger_router,
)
from app.review_api.routes import router as review_api_router
from app.mission_control_briefing.routes import router as mission_control_briefing_router
from app.mission_control_release.routes import router as mission_control_release_router
from app.executive_telemetry.routes import router as executive_telemetry_router
from app.missions.dependencies import get_mission_service
from app.missions.routers import router as missions_router, runtime_queue_router, templates_router
from app.security import get_api_key, get_owner_access_code, get_owner_session_secret, owner_cookie_secure, verify_owner_or_api_key
from app.routers.health import add_mission_control_cors_headers, allowed_mission_control_origins
from runtime.constitutional_orchestrator import AutonomyLevel, orchestrator as constitutional_orchestrator
from runtime.router_fastapi import router as runtime_router, science_router
from runtime.cds_router import router as cds_router
from runtime.constitutional_router import router as constitutional_router
from runtime.kernel_router import router as kernel_router
from runtime.orchestrator_router import router as orchestrator_router
from runtime.planner_router import router as planner_router
from runtime.autonomous_runner import enqueue_default_jobs, execute_next_job, run_job_logic
from runtime.runtime_engine import RuntimeEngine
from runtime.scheduler import CalyxHeartbeat

app = FastAPI()


@app.middleware("http")
async def mission_control_cors_on_all_responses(request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if (
        origin
        and origin.rstrip("/") in allowed_mission_control_origins()
        and "access-control-allow-origin" not in response.headers
    ):
        response.headers["Access-Control-Allow-Origin"] = origin
        existing_vary = response.headers.get("Vary")
        if existing_vary:
            if "origin" not in existing_vary.lower():
                response.headers["Vary"] = f"{existing_vary}, Origin"
        else:
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "accept, Content-Type, Authorization, X-API-Key"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response

DATABASE_URL = os.environ.get("DATABASE_URL")
RUNTIME_INTERVAL_FLAGS = ("CALYX_RUNTIME_INTERVAL_SECONDS", "OC_RUNNER_INTERVAL_SECONDS")
ACTIVE_MODE = os.environ.get("OC_RUNNER_ACTIVE_MODE", "true").lower() == "true"
RUNTIME_ENABLE_FLAGS = (
    "CALYX_AUTOLOOP_ENABLED",
    "OC_RUNNER_AUTOLOOP",
    "CALYX_RUNTIME_ENABLED",
    "AUTONOMOUS_RUNTIME_ENABLED",
    "RUNNER_ENABLED",
    "CALYX_AUTONOMOUS_ENABLED",
)
RUNTIME_DISABLE_FLAGS = (
    "CALYX_AUTONOMOUS_DISABLED",
    "OC_RUNNER_DISABLED",
    "CALYX_RUNTIME_DISABLED",
)

SCIENTIFIC_MODULES: list[dict[str, Any]] = [
    {
        "module_name": "pollinator_relationships",
        "state": "scientific_priority",
        "priority": 100,
        "job_name": "audit_missing_pollinator_data",
        "mission": "Identify orchid taxa missing pollinator data.",
    },
    {
        "module_name": "mycorrhiza_relationships",
        "state": "scientific_priority",
        "priority": 98,
        "job_name": "audit_missing_mycorrhizal_data",
        "mission": "Identify orchid taxa missing mycorrhizal data.",
    },
    {
        "module_name": "literature_extraction",
        "state": "scientific_priority",
        "priority": 96,
        "job_name": "audit_literature_extraction_coverage",
        "mission": "Audit literature extraction coverage.",
    },
    {
        "module_name": "ecological_relationship_graph",
        "state": "scientific_priority",
        "priority": 95,
        "job_name": "audit_ecological_relationship_graph_gaps",
        "mission": "Audit ecological relationship graph gaps.",
    },
    {
        "module_name": "traitbank_traits",
        "state": "scientific_priority",
        "priority": 94,
        "job_name": "audit_traitbank_trait_coverage",
        "mission": "Audit TraitBank and trait coverage.",
    },
    {
        "module_name": "conservation_habitat",
        "state": "scientific_priority",
        "priority": 93,
        "job_name": "audit_conservation_habitat_gaps",
        "mission": "Audit conservation and habitat data gaps.",
    },
    {
        "module_name": "image_species_evidence",
        "state": "scientific_priority",
        "priority": 90,
        "job_name": "audit_image_species_evidence_coverage",
        "mission": "Audit image and species evidence coverage.",
    },
    {
        "module_name": "frontend_knowledge_graph_integration",
        "state": "scientific_priority",
        "priority": 88,
        "job_name": "audit_frontend_relationship_cards",
        "mission": "Audit frontend relationship cards against backend data.",
    },
]

SUPPORT_MODULES: list[dict[str, Any]] = [
    {
        "module_name": "calyx_core_health",
        "state": "runtime_support",
        "priority": 80,
        "job_name": "optimize_calyx_core",
        "mission": "Check Calyx core health after scientific mission seeding.",
    },
    {
        "module_name": "constitutional_orchestrator",
        "state": "runtime_support",
        "priority": 85,
        "job_name": "optimize_constitutional_orchestrator",
        "mission": "Check Calyx constitutional guardrail and mission registry readiness.",
    },
    {
        "module_name": "judging",
        "state": "optional_low_priority",
        "priority": 25,
        "job_name": "optimize_judging",
        "mission": "Optional judging module maintenance when no scientific work is pending.",
    },
    {
        "module_name": "awards",
        "state": "optional_low_priority",
        "priority": 20,
        "job_name": "optimize_awards",
        "mission": "Optional awards module maintenance when no scientific work is pending.",
    },
]

MODULE_REGISTRY = SCIENTIFIC_MODULES + SUPPORT_MODULES
SCIENTIFIC_JOB_NAMES = {module["job_name"] for module in SCIENTIFIC_MODULES}
JOB_PRIORITIES = {module["job_name"]: module["priority"] for module in MODULE_REGISTRY}
JOB_MODULES = {module["job_name"]: module for module in MODULE_REGISTRY}
JOB_PRIORITY_SQL = "CASE job_name " + " ".join(
    f"WHEN '{job_name}' THEN {priority}" for job_name, priority in JOB_PRIORITIES.items()
) + " ELSE 0 END"


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for Calyx runner operations")
    return DATABASE_URL


def env_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def runtime_interval_seconds_from_env() -> int:
    for key in RUNTIME_INTERVAL_FLAGS:
        value = os.environ.get(key)
        if value is None:
            continue
        try:
            return max(5, int(value))
        except ValueError:
            return 30
    return 30


def autonomous_runtime_config_blocker() -> Optional[dict[str, str]]:
    for key in RUNTIME_DISABLE_FLAGS:
        if env_bool(os.environ.get(key)) is True:
            return {"key": key, "reason": "explicit_disable_flag"}

    for key in RUNTIME_ENABLE_FLAGS:
        if key in os.environ and env_bool(os.environ.get(key)) is False:
            return {"key": key, "reason": "explicit_enable_flag_false"}

    return None


def autonomous_runtime_enabled_by_config() -> bool:
    if autonomous_runtime_config_blocker() is not None:
        return False

    return any(env_bool(os.environ.get(key)) is True for key in RUNTIME_ENABLE_FLAGS)

AUTO_LOOP_ENABLED = autonomous_runtime_enabled_by_config()
AUTO_LOOP_INTERVAL_SECONDS = runtime_interval_seconds_from_env()
RUNTIME_WRITE_AUTH = [Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)]
RUNTIME_CORS = [Depends(add_mission_control_cors_headers)]


def auth_required_action(reason: str, *, risk: str = "medium") -> dict[str, Any]:
    return {
        "allowed": False,
        "state": "requires_owner_authorization",
        "auth": "owner_session_or_api_key_required",
        "risk": risk,
        "reason": reason,
    }


def runner_allowed_actions() -> dict[str, dict[str, Any]]:
    return {
        "runOnce": auth_required_action("Seeds runtime jobs and writes queue state.", risk="medium"),
        "seedMissions": auth_required_action("Seeds runtime mission jobs and writes queue state.", risk="medium"),
        "executeNext": auth_required_action("Executes one pending job and writes execution state.", risk="medium"),
        "executeAll": auth_required_action("Executes the full pending queue and may perform many writes.", risk="high"),
        "autonomousCycle": auth_required_action("Runs one autonomous worker cycle.", risk="medium"),
        "startRuntime": auth_required_action("Starts the autonomous runtime worker.", risk="high"),
        "stopRuntime": auth_required_action("Stops or disables the autonomous runtime worker.", risk="high"),
        "restartRuntime": auth_required_action("Restarts the autonomous runtime worker.", risk="high"),
    }


def evaluate_runtime_action(
    action: str,
    *,
    requested_autonomy_level: int = int(AutonomyLevel.SAFE_OPERATIONS),
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return constitutional_orchestrator.evaluate_action(
        mission_id="engineering",
        action=f"runtime:{action}",
        requested_autonomy_level=requested_autonomy_level,
        evidence=evidence or [f"route=/api/runner/{action}"],
        reversible=True,
        provenance_available=True,
    )


class VerificationRequest(BaseModel):
    source_context: Optional[str] = None


@app.get("/")
def read_root():
    return {"status": "Calyx Backend API running"}


@app.post("/verify")
def verify(request: VerificationRequest):
    return {"received": True, "source_context": request.source_context}


@app.get("/api/runner/health", dependencies=RUNTIME_CORS)
def runner_health():
    config = runtime_configuration()
    return {
        "status": "runner alive",
        "runtime_configured": not config["blockers"],
        "runtime_enabled": runtime_engine.status()["enabled"],
        "runtime_running": runtime_engine.status()["running"],
        "thread_alive": runtime_engine.status()["thread_alive"],
        "autoloop_enabled": config["autoloop_enabled"],
        "interval_seconds": config["interval_seconds"],
        "active_mode": ACTIVE_MODE,
        "mode": "build_046_scientific_priority_realignment",
        "runtime_mode": config["worker_mode"],
        "autonomous_runtime_blocker": autonomous_runtime_config_blocker(),
        "configuration": config,
        "runtime_engine": runtime_engine.status(),
        "allowedActions": runner_allowed_actions(),
    }


def runtime_configuration():
    blocker = autonomous_runtime_config_blocker()
    blockers: list[str] = []
    deployment_actions: list[str] = []
    if not get_api_key():
        blockers.append("CALYX_API_KEY is not configured")
        deployment_actions.append("Set CALYX_API_KEY to enable authenticated runtime operations.")
    if not get_owner_access_code():
        blockers.append("CALYX_OWNER_ACCESS_CODE is not configured")
        deployment_actions.append("Set CALYX_OWNER_ACCESS_CODE to enable owner login.")
    if not get_owner_session_secret():
        blockers.append("CALYX_OWNER_SESSION_SECRET is not configured")
        deployment_actions.append("Set CALYX_OWNER_SESSION_SECRET to enable signed owner sessions.")
    if blocker:
        blockers.append(f"{blocker['key']} blocks autonomous runtime")
    if not DATABASE_URL:
        blockers.append("DATABASE_URL is not configured")
        deployment_actions.append("Set DATABASE_URL before enabling runtime workers.")
    return {
        "autoloop_enabled": AUTO_LOOP_ENABLED,
        "interval_seconds": AUTO_LOOP_INTERVAL_SECONDS,
        "worker_mode": "active" if ACTIVE_MODE else "dry_run",
        "blockers": blockers,
        "deployment_actions": deployment_actions,
    }


calyx_heartbeat = CalyxHeartbeat()
runtime_engine = RuntimeEngine(
    heartbeat=calyx_heartbeat.run_once,
    enqueue_jobs=enqueue_default_jobs,
    execute_jobs=execute_next_job,
    interval_seconds=AUTO_LOOP_INTERVAL_SECONDS,
    enabled=AUTO_LOOP_ENABLED,
)


@app.on_event("startup")
def startup_event():
    if AUTO_LOOP_ENABLED:
        runtime_engine.start()
    try:
        from app.routers.owner_operations import load_revoked_nonces
        load_revoked_nonces()
    except Exception:
        pass


@app.on_event("shutdown")
def shutdown_event():
    runtime_engine.stop()


app.include_router(health.router)
app.include_router(calyx_core.router)
app.include_router(awards.router)
app.include_router(entries.router)
app.include_router(feedback.router)
app.include_router(harvesters.router, dependencies=[Depends(add_mission_control_cors_headers)])
app.include_router(judging.router)
app.include_router(reference_docs.router)
app.include_router(intake_router)
app.include_router(semantic_router)
app.include_router(source_registry_router)
app.include_router(document_import_router)
app.include_router(document_intelligence_router)
app.include_router(semantic_index_router)
app.include_router(evidence_retrieval_router)
app.include_router(candidate_knowledge_router)
app.include_router(evidence_aggregation_router)
app.include_router(design_intelligence_router)
app.include_router(design_planning_router)
app.include_router(implementation_planning_router)
app.include_router(scientific_interpretation_router)
app.include_router(ontology_router)
app.include_router(concepts_router)
app.include_router(brain_router)
app.include_router(literature_extraction_router)
app.include_router(publication_router)
app.include_router(research_workspace_router)
app.include_router(reasoning_ledger_router)
app.include_router(reasoning_ledger_project_router)
app.include_router(review_api_router)
app.include_router(mission_control_briefing_router)
app.include_router(mission_control_release_router)
app.include_router(executive_telemetry_router)
app.include_router(missions_router)
app.include_router(templates_router)
app.include_router(runtime_queue_router)
app.include_router(runtime_router)
app.include_router(science_router)
app.include_router(cds_router)
app.include_router(constitutional_router)
app.include_router(kernel_router)
app.include_router(orchestrator_router)
app.include_router(planner_router)

from app.routers import orchid_widgets

app.include_router(orchid_widgets.router)

from app.routers import knowledge_graph

app.include_router(knowledge_graph.router)
