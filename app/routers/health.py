from fastapi import APIRouter, Depends, Request, Response

from app.routers.harvesters import router as harvesters_router
from app.routers.mission_control import router as mission_control_router
from runtime.connector_routes import router as connector_router
from runtime.router_fastapi import config_router, infrastructure_router

ALLOWED_MISSION_CONTROL_ORIGINS = {
    "https://orchid-continuum-frontend-vof6.onrender.com",
    "https://orchidcontinuum.org",
    "https://www.orchidcontinuum.org",
}

router = APIRouter(tags=["health"])


def add_mission_control_cors_headers(request: Request, response: Response) -> None:
    """Attach safe browser CORS headers for read-only Mission Control telemetry.

    This is scoped to /api/mission-control/* while preserving the backend's
    existing runtime safety posture. It permits only known Orchid Continuum
    browser origins and does not enable credentials or write operations.
    """
    origin = request.headers.get("origin")
    if origin in ALLOWED_MISSION_CONTROL_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Max-Age"] = "86400"


@router.options("/api/mission-control/{full_path:path}")
def mission_control_options(full_path: str, request: Request, response: Response):
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
router.include_router(harvesters_router)
router.include_router(config_router)
router.include_router(infrastructure_router)
router.include_router(connector_router)
