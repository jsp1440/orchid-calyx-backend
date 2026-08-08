"""Protected Mission Control routes for review-only licensed-media persistence."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.licensed_media_persistence import LicensedMediaPersistenceService

router = APIRouter(
    prefix="/brain/mission-control/media",
    tags=["mission-control-media"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


def _service() -> LicensedMediaPersistenceService:
    root = Path(os.environ.get("CALYX_MEDIA_PERSISTENCE_PATH", "/tmp/calyx/media-persistence"))
    maximum = int(os.environ.get("CALYX_MEDIA_MAX_RECORDS", "2000"))
    return LicensedMediaPersistenceService(root, maximum_records=maximum)


def _taxonomy_staging_path() -> Path | None:
    value = os.environ.get("CALYX_TAXONOMY_REVIEW_STAGING_PATH", "").strip()
    return Path(value) if value else None


class MediaIntakeRequest(BaseModel):
    records: list[dict[str, Any]] = Field(min_length=1, max_length=2000)


class StageRequest(BaseModel):
    batch_size: int = Field(default=500, ge=1, le=5000)


@router.post("/intake")
def intake_media(request: MediaIntakeRequest) -> dict:
    try:
        return _service().intake_records(
            request.records,
            taxonomy_staging_path=_taxonomy_staging_path(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{batch_id}/stage")
def stage_media(batch_id: str, request: StageRequest) -> dict:
    try:
        return _service().project_staging(batch_id, batch_size=request.batch_size)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{batch_id}/review-queue")
def media_review_queue(
    batch_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    try:
        return _service().review_queue(batch_id, offset=offset, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{batch_id}/readiness")
def media_readiness(batch_id: str) -> dict:
    try:
        return _service().readiness(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
