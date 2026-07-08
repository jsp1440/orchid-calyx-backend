from fastapi import APIRouter, Depends, Response

from app.routers.mission_control import router as mission_control_router
from runtime.connector_routes import router as connector_router
from runtime.router_fastapi import config_router, infrastructure_router

ALLOWED_MISSION_CONTROL_ORIGINS = {
    "https://orchid-continuum-frontend-vof6.onrender.com",
    "https://orchidcontinuum.org",
    "https://www.orchidcontinuum.org",
}

router = APIRouter(tags=["health"])


def add_mission_control_cors_headers(response: Response) -> None:
    """Attach safe browser CORS headers for read-only Mission Control routes.

    This is intentionally scoped to Mission Control telemetry while the backend
    awaits a broader app-level CORSMiddleware cleanup. It allows the deployed
    frontend and canonical Orchid Continuum domains to read GET telemetry
    responses without enabling credentials or write actions.
    """
    response.headers["Access-Control-Allow-Origin"] = "https://orchid-continuum-frontend-vof6.onrender.com"
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Max-Age"] = "86400"


@router.options("/api/mission-control/{full_path:path}")
def mission_control_options(full_path: str, response: Response):
    add_mission_control_cors_headers(response)
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
router.include_router(config_router)
router.include_router(infrastructure_router)
router.include_router(connector_router)
