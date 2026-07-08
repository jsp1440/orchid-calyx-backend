from fastapi import APIRouter

from app.routers.mission_control import router as mission_control_router
from runtime.connector_routes import router as connector_router
from runtime.router_fastapi import config_router, infrastructure_router

router = APIRouter(tags=["health"])


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


router.include_router(mission_control_router)
router.include_router(config_router)
router.include_router(infrastructure_router)
router.include_router(connector_router)
