"""FastAPI endpoints for BUILD-013 Brain integration."""

from __future__ import annotations

from fastapi import APIRouter

from .brain_integration import BrainIntegrationWorker
from .runtime_planner import RuntimePlanner


router = APIRouter(prefix="/api/brain", tags=["Orchid Continuum Brain"])


def queue_item(module_name: str, module_id: str, action: str) -> dict:
    for item in RuntimePlanner().queue()["queue"]:
        if item["module_name"] == module_name:
            return item
    return {
        "module_id": module_id,
        "module_name": module_name,
        "job_name": f"cds:{module_id}",
        "action": action,
    }


def database_queue_item() -> dict:
    return queue_item("DatabaseInspector", "CDS-ENG-002", "Inspect live Brain database state")


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
            "/api/brain/schemas",
            "/api/brain/tables",
            "/api/brain/health",
            "/api/brain/audit",
            "/api/brain/recommendations",
            "/api/brain/engineering-memory",
            "/api/brain/dependency-intelligence",
            "/api/brain/cognitive-audit",
        ],
    }


@router.get("/status")
def brain_status():
    result = BrainIntegrationWorker(database_queue_item()).database_inspector()
    return {
        "build": "BUILD-013",
        "connected": result.get("brain_connection") == "connected",
        "status": result.get("status"),
        "message": result.get("message"),
        "schema_count": result.get("schema_count"),
        "table_count_sampled": result.get("table_count_sampled"),
        "recommendations": result.get("recommendations", []),
    }


@router.get("/schemas")
def brain_schemas():
    result = BrainIntegrationWorker(database_queue_item()).database_inspector()
    return {
        "build": "BUILD-013",
        "connected": result.get("brain_connection") == "connected",
        "schemas": result.get("schemas", []),
        "status": result.get("status"),
        "message": result.get("message"),
    }


@router.get("/tables")
def brain_tables():
    result = BrainIntegrationWorker(database_queue_item()).database_inspector()
    return {
        "build": "BUILD-013",
        "connected": result.get("brain_connection") == "connected",
        "tables": result.get("tables_sample", []),
        "status": result.get("status"),
        "message": result.get("message"),
    }


@router.get("/health")
def brain_health():
    result = BrainIntegrationWorker(database_queue_item()).database_inspector()
    connected = result.get("brain_connection") == "connected"
    return {
        "build": "BUILD-013",
        "health": "healthy" if connected else "degraded",
        "database_inspector": result,
    }


@router.get("/engineering-memory")
def engineering_memory_status():
    item = queue_item("EngineeringMemoryHarvester", "CDS-ENG-001", "Harvest BUILD reports")
    return BrainIntegrationWorker(item).engineering_memory_harvester()


@router.get("/dependency-intelligence")
def dependency_intelligence_status():
    item = queue_item("DependencyIntelligence", "CDS-SCI-001", "Inspect dependency graph")
    return BrainIntegrationWorker(item).dependency_intelligence()


@router.get("/cognitive-audit")
def cognitive_audit_status():
    item = queue_item("CognitiveAudit", "CDS-COG-001", "Audit runtime readiness")
    return BrainIntegrationWorker(item).cognitive_audit()


@router.get("/audit")
def brain_audit():
    return {"build": "BUILD-013", "audit": cognitive_audit_status()}


@router.get("/recommendations")
def brain_recommendations():
    queue_items = RuntimePlanner().queue()["queue"]
    recommendations = []
    for item in queue_items:
        result = BrainIntegrationWorker(item).execute()
        recommendations.extend(result.get("recommendations", []))
    return {
        "build": "BUILD-013",
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
    }


@router.post("/refresh")
def brain_refresh():
    return {
        "build": "BUILD-013",
        "status": "refreshed",
        "brain_status": brain_status(),
        "audit": brain_audit(),
    }
