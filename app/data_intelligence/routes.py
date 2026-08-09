from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.security import verify_owner_or_api_key

from .models import AnalysisPlan, CompileIntentIn, DataIntelligenceError
from .repository import FileDatasetRepository
from .service import DataIntelligenceService

router = APIRouter(prefix="/data", tags=["data-intelligence"])
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]


def _subject(auth: dict) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return subject


def _service() -> DataIntelligenceService:
    root = os.environ.get("CALYX_DATA_INTELLIGENCE_ROOT", "data/data_intelligence")
    return DataIntelligenceService(FileDatasetRepository(root))


def _translate(exc: Exception) -> None:
    if isinstance(exc, DataIntelligenceError):
        status = (
            404
            if exc.code in {"DATASET_VERSION_NOT_FOUND", "ANALYSIS_NOT_FOUND"}
            else 422
        )
        raise HTTPException(
            status,
            detail={"code": exc.code, "details": exc.details},
        ) from exc
    raise exc


@router.post("/projects/{project_id}/datasets", status_code=201)
async def ingest_dataset(
    project_id: str,
    auth: Auth,
    file: UploadFile = File(...),
    logical_name: str | None = Query(default=None, min_length=1, max_length=200),
):
    owner = _subject(auth)
    try:
        data = await file.read()
        name = logical_name or file.filename or "dataset"
        return _service().ingest(
            owner=owner,
            project_id=project_id,
            logical_name=name,
            filename=file.filename or name,
            data=data,
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/profile"
)
def get_profile(
    project_id: str,
    dataset_id: str,
    version_id: str,
    auth: Auth,
):
    owner = _subject(auth)
    service = _service()
    try:
        dataset = service.repository.get(
            owner,
            project_id,
            dataset_id,
            version_id,
        )
        return service.profile(
            owner=owner,
            project_id=project_id,
            dataset=dataset,
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/projects/{project_id}/plans/compile")
def compile_plan(project_id: str, payload: CompileIntentIn, auth: Auth):
    owner = _subject(auth)
    service = _service()
    try:
        service.repository.get(
            owner,
            project_id,
            payload.dataset.dataset_id,
            payload.dataset.version_id,
        )
        return service.compile_intent(
            dataset_id=payload.dataset.dataset_id,
            version_id=payload.dataset.version_id,
            intent=payload.intent,
        ).canonical_payload()
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/projects/{project_id}/analyses", status_code=201)
def execute_plan(project_id: str, plan: AnalysisPlan, auth: Auth):
    owner = _subject(auth)
    try:
        return _service().execute(
            owner=owner,
            project_id=project_id,
            plan=plan,
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/"
    "analyses/{analysis_id}"
)
def get_analysis(
    project_id: str,
    dataset_id: str,
    version_id: str,
    analysis_id: str,
    auth: Auth,
):
    owner = _subject(auth)
    try:
        return _service().repository.get_analysis(
            owner,
            project_id,
            dataset_id,
            version_id,
            analysis_id,
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.post(
    "/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/"
    "analyses/{analysis_id}/rerun"
)
def rerun_analysis(
    project_id: str,
    dataset_id: str,
    version_id: str,
    analysis_id: str,
    auth: Auth,
):
    owner = _subject(auth)
    try:
        return _service().rerun(
            owner=owner,
            project_id=project_id,
            dataset_id=dataset_id,
            version_id=version_id,
            analysis_id=analysis_id,
        )
    except Exception as exc:
        _translate(exc)
        raise
