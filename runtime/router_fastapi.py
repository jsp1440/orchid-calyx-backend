"""FastAPI router for Calyx Runtime v0.1."""
from fastapi import APIRouter
from .scheduler import CalyxHeartbeat

router = APIRouter(prefix="/api/runtime", tags=["Calyx Runtime"])


@router.get("/heartbeat")
def runtime_heartbeat():
    return CalyxHeartbeat().run_once()


@router.get("/health")
def runtime_health():
    return {"runtime": CalyxHeartbeat().run_once()}
