"""Protected Mission Control routes for review-only taxonomy release intake."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.taxonomy_release_intake import TaxonomyReleaseIntakeService

router = APIRouter(
    prefix="/brain/mission-control/taxonomy/releases",
    tags=["mission-control-taxonomy"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


def _service() -> TaxonomyReleaseIntakeService:
    root = Path(os.environ.get("CALYX_TAXONOMY_INTAKE_PATH", "/tmp/calyx/taxonomy-intake"))
    maximum = int(os.environ.get("CALYX_TAXONOMY_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
    return TaxonomyReleaseIntakeService(root, maximum_bytes=maximum)


def _active_baseline_path() -> Path | None:
    value = os.environ.get("CALYX_TAXONOMY_ACTIVE_BASELINE_PATH", "").strip()
    return Path(value) if value else None


class StageRequest(BaseModel):
    batch_size: int = Field(default=500, ge=1, le=5000)


@router.post("/intake")
async def intake_release(
    source: Annotated[UploadFile, File()],
    expected_label: Annotated[str | None, Form()] = None,
) -> dict:
    payload = await source.read()
    try:
        return _service().intake_bytes(
            source.filename or "taxonomy-release.csv",
            payload,
            expected_label=expected_label,
            baseline_path=_active_baseline_path(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{release_id}/stage")
def stage_release(release_id: str, request: StageRequest) -> dict:
    try:
        return _service().project_staging(release_id, batch_size=request.batch_size)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{release_id}/review-queue")
def release_review_queue(
    release_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    try:
        return _service().review_queue(release_id, offset=offset, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{release_id}/readiness")
def release_readiness(release_id: str) -> dict:
    try:
        return _service().readiness(release_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
