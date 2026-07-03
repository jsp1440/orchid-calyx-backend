from fastapi import APIRouter

from runtime.router_fastapi import router as runtime_router

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


router.include_router(runtime_router)
