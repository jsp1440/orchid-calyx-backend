"""FastAPI endpoints for BUILD-014 Autonomous Discovery."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security import verify_api_key
from .autonomous_discovery import AutonomousDiscoveryEngine


router = APIRouter(prefix="/api/runner", tags=["Calyx Autonomous Discovery"])
WRITE_AUTH = [Depends(verify_api_key)]


def engine() -> AutonomousDiscoveryEngine:
    return AutonomousDiscoveryEngine()


@router.get("/discover")
def get_discovery():
    return engine().cached_or_discover()


@router.post("/discover", dependencies=WRITE_AUTH)
def run_discovery():
    return engine().discover(write_cache=True)


@router.get("/modules")
def discovered_modules():
    return engine().modules()


@router.get("/capabilities")
def discovered_capabilities():
    return engine().capabilities()


@router.get("/graph")
def discovered_graph():
    return engine().graph()


@router.get("/recommendations")
def discovered_recommendations():
    return engine().recommendations()


@router.get("/schedule")
def discovered_schedule():
    return engine().schedule()


@router.get("/discovery-dashboard")
def discovery_dashboard():
    payload = engine().cached_or_discover()
    return {"build": "BUILD-014", "dashboard": payload.get("summary", {}), "recommendations": payload.get("recommendations", [])[:5]}


@router.post("/rebuild", dependencies=WRITE_AUTH)
def rebuild_discovery():
    return engine().discover(write_cache=True)
