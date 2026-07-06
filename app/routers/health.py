from fastapi import APIRouter

from runtime.connector_routes import router as connector_router
from runtime.orchestrator_router import router as orchestrator_router
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


router.include_router(config_router)
router.include_router(infrastructure_router)
router.include_router(connector_router)
router.include_router(orchestrator_router)
