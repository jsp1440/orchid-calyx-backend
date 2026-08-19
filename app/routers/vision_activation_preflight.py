"""Owner-gated read-only activation preflight for Calyx Vision."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.security import verify_owner_or_api_key
from app.vision_lexicon.preflight import vision_activation_preflight

router = APIRouter(prefix="/api/vision-lexicon", tags=["vision-lexicon-activation"])
AuthDep = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


@router.get("/activation-preflight")
def activation_preflight(_: AuthDep) -> dict[str, Any]:
    """Inspect activation prerequisites without migrations, flag changes, or inference."""
    return vision_activation_preflight()
