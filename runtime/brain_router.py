"""FastAPI endpoints for BUILD-013 Brain integration."""

from __future__ import annotations

from fastapi import APIRouter

from .brain_integration import BrainIntegrationWorker
from .runtime_planner import RuntimePlanner


router = APIRouter(prefix="/api/brain", tags=["Orchid Continuum Brain"])


@router.get("/status")
def brain_status():
    item = {
        "module_id": "CDS-ENG-002",
        "module_name": "DatabaseInspector",
        "job_name": "cds:CDS-ENG-002",
        "action": "Inspect live Brain database state",
    }
    return BrainIntegrationWorker(item).database_inspector()


@router.get("/engineering-memory")
def engineering_memory_status():
    item = {
        "module_id": "CDS-ENG-001",
        "module_name": "EngineeringMemoryHarvester",
        "job_name": "cds:CDS-ENG-001",
        "action": "Harvest BUILD reports",
    }
    return BrainIntegrationWorker(item).engineering_memory_harvester()


@router.get("/dependency-intelligence")
def dependency_intelligence_status():
    item = {
        "module_id": "CDS-SCI-001",
        "module_name": "DependencyIntelligence",
        "job_name": "cds:CDS-SCI-001",
        "action": "Inspect dependency graph",
    }
    return BrainIntegrationWorker(item).dependency_intelligence()


@router.get("/cognitive-audit")
def cognitive_audit_status():
    item = {
        "module_id": "CDS-COG-001",
        "module_name": "CognitiveAudit",
        "job_name": "cds:CDS-COG-001",
        "action": "Audit runtime readiness",
    }
    return BrainIntegrationWorker(item).cognitive_audit()


@router.get("/summary")
def brain_summary():
    queue = RuntimePlanner().queue()
    return {
        "build": "BUILD-013",
        "status": "brain_integration_available",
        "queue_depth": queue.get("queue_depth"),
        "first_live_modules": [
            "DatabaseInspector",
            "EngineeringMemoryHarvester",
            "DependencyIntelligence",
            "CognitiveAudit",
        ],
        "endpoints": [
            "/api/brain/status",
            "/api/brain/engineering-memory",
            "/api/brain/dependency-intelligence",
            "/api/brain/cognitive-audit",
        ],
    }
