"""FastAPI endpoints for BUILD-012C runtime planning."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .cds_loader import CDSRegistryError, clear_cds_cache
from .runtime_planner import RuntimePlanner


router = APIRouter(prefix="/api/runner", tags=["Calyx Runtime Planner"])


def planner() -> RuntimePlanner:
    return RuntimePlanner()


@router.get("/discovery")
def runner_discovery():
    try:
        return planner().discovery()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dependencies")
def runner_dependencies():
    try:
        return planner().dependency_graph()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/plan")
def runner_plan():
    try:
        return planner().plan()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/queue")
def runner_queue():
    try:
        return planner().queue()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild-plan")
def runner_rebuild_plan():
    try:
        clear_cds_cache()
        return {
            "status": "rebuilt",
            "discovery": planner().discovery(),
            "plan": planner().plan(),
            "queue": planner().queue(),
        }
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
