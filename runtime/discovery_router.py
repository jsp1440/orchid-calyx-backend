"""FastAPI endpoints for BUILD-014 autonomous discovery."""

from __future__ import annotations

from fastapi import APIRouter

from .autonomous_discovery import DiscoveryEngine


router = APIRouter(prefix="/api/runner", tags=["Calyx Autonomous Discovery"])


def engine() -> DiscoveryEngine:
    return DiscoveryEngine()


@router.get("/discover")
def get_discovery():
    return engine().cached_or_discover()


@router.post("/discover")
def post_discovery():
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


@router.get("/schedule")
def discovered_schedule():
    return engine().schedule()


@router.get("/recommendations")
def discovered_recommendations():
    return engine().recommendation_report()


@router.get("/discovery-dashboard")
def discovery_dashboard():
    return engine().dashboard_report()


@router.post("/rebuild")
def rebuild_discovery():
    return engine().discover(write_cache=True)
