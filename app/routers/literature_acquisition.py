"""Protected Mission Control routes for bounded Literature Intelligence acquisition."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.literature_acquisition import LiteratureAcquisitionService

router = APIRouter(
    prefix="/brain/mission-control/literature",
    tags=["mission-control-literature"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


def _service() -> LiteratureAcquisitionService:
    root = Path(os.environ.get("CALYX_LITERATURE_ACQUISITION_PATH", "/tmp/calyx/literature-acquisition"))
    maximum = int(os.environ.get("CALYX_LITERATURE_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
    return LiteratureAcquisitionService(root, maximum_bytes=maximum)


def _taxonomy_staging_path() -> Path | None:
    value = os.environ.get("CALYX_TAXONOMY_REVIEW_STAGING_PATH", "").strip()
    return Path(value) if value else None


class TaxonReconciliationRequest(BaseModel):
    taxa: list[dict[str, str]] = Field(default_factory=list, max_length=1000)


class CandidateHandoffRequest(BaseModel):
    candidates: list[dict[str, Any]] = Field(min_length=1, max_length=500)


@router.post("/intake")
async def intake_literature(
    source: Annotated[UploadFile, File()],
    source_ref: Annotated[str | None, Form()] = None,
) -> dict:
    payload = await source.read()
    try:
        return _service().intake_bytes(
            source.filename or "literature-source.txt",
            payload,
            source_ref=source_ref,
            taxonomy_staging_path=_taxonomy_staging_path(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{run_id}/reconcile-taxa")
def reconcile_taxa(run_id: str, request: TaxonReconciliationRequest) -> dict:
    try:
        return _service().reconcile_taxa(
            run_id,
            request.taxa,
            taxonomy_staging_path=_taxonomy_staging_path(),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{run_id}/candidate-handoffs")
def candidate_handoffs(run_id: str, request: CandidateHandoffRequest) -> dict:
    try:
        return _service().handoff_candidates(run_id, request.candidates)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{run_id}/evidence")
def literature_evidence(
    run_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    try:
        return _service().evidence(run_id, offset=offset, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{run_id}/readiness")
def literature_readiness(run_id: str) -> dict:
    try:
        return _service().readiness(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
