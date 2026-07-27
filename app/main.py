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
from app.literature_extraction.routes import router as literature_extraction_router
from app.publication.routers import router as publication_router
from app.research_workspace.routes import router as research_workspace_router
from app.review_api.routes import router as review_api_router
from app.mission_control_briefing.routes import router as mission_control_briefing_router
from app.mission_control_release.routes import router as mission_control_release_router
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
        "module_name": "traitbank",
        "state": "scientific_priority",
        "priority": 94,
        "job_name": "audit_traitbank_trait_coverage",
        "mission": "Audit TraitBank trait coverage and normalization gaps.",
    },
    {
        "module_name": "ecological_relationship_graph",
        "state": "scientific_priority",
        "priority": 92,
        "job_name": "audit_ecological_relationship_graph_gaps",
        "mission": "Audit ecological relationship graph gaps.",
    },
    {
        "module_name": "image_species_evidence",
        "state": "scientific_priority",
        "priority": 90,
        "job_name": "audit_image_species_evidence_coverage",
        "mission": "Audit image-to-species evidence coverage.",
    },
    {
        "module_name": "conservation_habitat",
        "state": "scientific_priority",
        "priority": 88,
        "job_name": "audit_conservation_habitat_gaps",
        "mission": "Audit conservation and habitat gaps.",
    },
]


class VerificationRequest(BaseModel):
    source_context: Optional[dict[str, Any]] = None


@app.post("/verify")
def verify(request: VerificationRequest):
    return {"received": True, "source_context": request.source_context}


@app.get("/api/runner/health", dependencies=[Depends(add_mission_control_cors_headers)])
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
app.include_router(literature_extraction_router)
app.include_router(publication_router)
app.include_router(research_workspace_router)
app.include_router(review_api_router)
app.include_router(mission_control_briefing_router)
app.include_router(mission_control_release_router)
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
