"""Read-only Mission Control zero-day readiness endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.security_readiness import Exposure, READINESS_TARGETS_MINUTES, closure_gate

router = APIRouter(prefix="/api/mission-control/security", tags=["mission-control", "security"])


class ExposureRequest(BaseModel):
    affected_assets: int = Field(ge=0)
    internet_exposure: int = Field(ge=1, le=5)
    privilege: int = Field(ge=1, le=5)
    connectivity: int = Field(ge=1, le=5)
    data_sensitivity: int = Field(ge=1, le=5)
    runtime_reachable: bool = True
    known_exploit: bool = False
    compensating_control: bool = False


class ClosureRequest(BaseModel):
    evidence: list[str] = Field(default_factory=list)


@router.get("/readiness")
def readiness() -> dict:
    return {
        "status": "foundation_active",
        "targets_minutes": READINESS_TARGETS_MINUTES,
        "containment_mode": "owner_approval_required",
        "parallel_delivery_preserved": True,
    }


@router.post("/exposure")
def score_exposure(request: ExposureRequest) -> dict:
    return Exposure(**request.model_dump()).payload()


@router.post("/closure")
def verify_closure(request: ClosureRequest) -> dict:
    return closure_gate(request.evidence)
