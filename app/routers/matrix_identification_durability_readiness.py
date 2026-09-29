"""Owner-gated read-only durability readiness API for the Matrix scientific trail."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.matrix_member_access import owner_or_matrix_member
from app.security import verify_owner_or_api_key
from runtime.matrix_identification_durability_readiness import (
    matrix_durability_readiness,
)

router = APIRouter(
    prefix="/api/matrix-identification",
    tags=["matrix-identification-durability-readiness"],
    # Default deny: owner/API key only; a verified member gets 403 OWNER_ACCESS_REQUIRED.
    dependencies=[Depends(owner_or_matrix_member)],
)


@router.get("/persistence-readiness")
def get_matrix_persistence_readiness(
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Return the ordered deployment-readiness contract without changing state."""
    return matrix_durability_readiness()
