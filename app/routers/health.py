import os
from fastapi import APIRouter, Depends, Request, Response

from app.routers.calyx_queue import router as calyx_queue_router
from app.routers.executive import router as executive_router
from app.routers.mission_control import router as mission_control_router
from app.routers.owner_operations import router as owner_operations_router
from app.routers.owner_session_token import router as owner_session_token_router
from app.routers.scientific_intelligence import router as scientific_intelligence_router
from runtime.connector_routes import router as connector_router
from runtime.router_fastapi import config_router, infrastructure_router

ALLOWED_MISSION_CONTROL_ORIGINS = {
    "https://orchid-continuum-frontend-vof6.onrender.com",
    "https://orchidcontinuum.org",
    "https://www.orchidcontinuum.org",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
}
def allowed_mission_control_origins() -> set[str]:
    return ALLOWED_MISSION_CONTROL_ORIGINS | {item.strip().rstrip("/") for item in os.getenv("CORS_ALLOW_ORIGIN", "").split(",") if item.strip() and item.strip() != "*"}

router = APIRouter(tags=["health"])


def add_mission_control_cors_headers(request: Request, response: Response) -> None:
    """Attach safe browser CORS headers for Mission Control telemetry and owner operations."""
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") in allowed_mission_control_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "accept, Content-Type, Authorization, X-API-Key, X-Orchid-Actor"
        response.headers["Access-Control-Max-Age"] = "86400"


@router.options("/api/mission-control/{full_path:path}")
def mission_control_options(full_path: str, request: Request, response: Response):
    add_mission_control_cors_headers(request, response)
    return {"status": "ok", "path": full_path}


@router.options("/api/executive/{full_path:path}")
def executive_options(full_path: str, request: Request, response: Response):
    add_mission_control_cors_headers(request, response)
    return {"status": "ok", "path": full_path}


@router.options("/api/scientific-intelligence/{full_path:path}")
def scientific_intelligence_options(full_path: str, request: Request, response: Response):
    add_mission_control_cors_headers(request, response)
    return {"status": "ok", "path": full_path}


@router.options("/api/calyx-queue/{full_path:path}")
def calyx_queue_options(full_path: str, request: Request, response: Response):
    add_mission_control_cors_headers(request, response)
    return {"status": "ok", "path": full_path}


@router.options("/api/runner/{full_path:path}")
def runner_options(full_path: str, request: Request, response: Response):
    add_mission_control_cors_headers(request, response)
    return {"status": "ok", "path": full_path}


@router.options("/api/harvesters/{full_path:path}")
def harvesters_options(full_path: str, request: Request, response: Response):
    add_mission_control_cors_headers(request, response)
    return {"status": "ok", "path": full_path}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system/status")
def system_status():
    return {
        "status": "ok",
        "service": "orchid-continuum",
        "backend": "calyx",
    }


router.include_router(mission_control_router, dependencies=[Depends(add_mission_control_cors_headers)])
router.include_router(owner_operations_router, dependencies=[Depends(add_mission_control_cors_headers)])
router.include_router(owner_session_token_router, dependencies=[Depends(add_mission_control_cors_headers)])
router.include_router(executive_router, dependencies=[Depends(add_mission_control_cors_headers)])
router.include_router(scientific_intelligence_router, dependencies=[Depends(add_mission_control_cors_headers)])
router.include_router(calyx_queue_router, dependencies=[Depends(add_mission_control_cors_headers)])
router.include_router(config_router)
router.include_router(infrastructure_router)
router.include_router(connector_router)
