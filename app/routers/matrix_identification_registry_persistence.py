"""Read-only persistence readiness API for immutable Matrix registry packages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.security import verify_owner_or_api_key
from runtime.matrix_identification_registry import registry_persistence_status
from runtime.matrix_identification_registry_preflight import (
    matrix_registry_persistence_preflight,
)

router = APIRouter(
    prefix="/api/matrix-identification/registry",
    tags=["matrix-identification-registry-persistence"],
)


@router.get("/persistence-status")
def get_registry_persistence_status(
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    return registry_persistence_status()


@router.get("/persistence-preflight")
def get_registry_persistence_preflight(
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    return matrix_registry_persistence_preflight()
