"""Protected Mission Control routes for bounded occurrence persistence."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.occurrence_persistence import OccurrencePersistenceService

router = APIRouter(
    prefix="/brain/mission-control/occurrences",
    tags=["mission-control-occurrences"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


def _service() -> OccurrencePersistenceService:
    root = Path(os.environ.get("CALYX_OCCURRENCE_PATH", "/tmp/calyx/occurrences"))
    maximum_records = int(os.environ.get("CALYX_OCCURRENCE_MAX_RECORDS", "5000"))
    maximum_bytes = int(os.environ.get("CALYX_OCCURRENCE_MAX_BYTES", str(25 * 1024 * 1024)))
    return OccurrencePersistenceService(
        root,
        maximum_records=maximum_records,
        maximum_bytes=maximum_bytes,
    )


def _taxonomy_staging_path() -> Path | None:
    value = os.environ.get("CALYX_TAXONOMY_REVIEW_STAGING_PATH", "").strip()
    return Path(value) if value else None


class OccurrenceIntakeRequest(BaseModel):
    source: str
    records: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class StageRequest(BaseModel):
    batch_size: int = Field(default=500, ge=1, le=5000)


@router.post("/intake")
def intake_occurrences(request: Annotated[OccurrenceIntakeRequest, Body()]) -> dict[str, Any]:
    try:
        return _service().intake_records(
            request.source,
            request.records,
            taxonomy_staging_path=_taxonomy_staging_path(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{batch_id}/stage")
def stage_occurrences(batch_id: str, request: StageRequest) -> dict[str, Any]:
    try:
        return _service().project_staging(batch_id, batch_size=request.batch_size)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{batch_id}/review-queue")
def occurrence_review_queue(
    batch_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    try:
        return _service().review_queue(batch_id, offset=offset, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{batch_id}/readiness")
def occurrence_readiness(batch_id: str) -> dict[str, Any]:
    try:
        return _service().readiness(batch_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
