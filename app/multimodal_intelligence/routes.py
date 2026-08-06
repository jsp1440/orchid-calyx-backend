from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.security import verify_owner_or_api_key

from .status import capability_status

router = APIRouter(
    prefix="/api/mission-control/multimodal-intelligence",
    tags=["multimodal-intelligence"],
)

AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


@router.get("/status")
def status(auth: AuthDependency) -> dict:
    del auth
    return capability_status()
