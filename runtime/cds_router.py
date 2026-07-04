"""FastAPI endpoints for the Calyx Development Suite registry."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .cds_loader import CDSRegistryError, clear_cds_cache, get_cds_loader


router = APIRouter(prefix="/api/cds", tags=["Calyx Development Suite"])


@router.get("/summary")
def cds_summary():
    try:
        return get_cds_loader().summary()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/modules")
def cds_modules():
    try:
        return {"modules": get_cds_loader().modules()}
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/modules/{module_id}")
def cds_module(module_id: str):
    try:
        return get_cds_loader().module(module_id)
    except CDSRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dashboard")
def cds_dashboard():
    try:
        return get_cds_loader().dashboard()
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/priorities")
def cds_priorities():
    try:
        return {"priorities": get_cds_loader().priorities()}
    except CDSRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/reload")
def cds_reload():
    clear_cds_cache()
    return {"status": "reloaded", "summary": get_cds_loader().summary()}
