"""Authenticated HTTP surface for contextual evidence feedback."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .models import FeedbackClass, ObjectType
from .repository import (
    EvidenceFeedbackRepositoryError,
    FileEvidenceFeedbackRepository,
)
from .service import EvidenceFeedbackService

router = APIRouter(prefix="/evidence-feedback", tags=["evidence-feedback"])
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]


class EvidenceObjectIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=500)
    object_type: ObjectType
    payload: dict[str, Any]
    previous_version_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )


class EvidenceFeedbackIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=500)
    object_version_hash: str = Field(min_length=64, max_length=64)
    object_type: ObjectType
    page_context: str = Field(min_length=1, max_length=2000)
    feedback_class: FeedbackClass
    statement: str = Field(min_length=1, max_length=20000)
    proposed_replacement: str | None = Field(default=None, max_length=20000)
    citation: str | None = Field(default=None, max_length=4000)
    source_partner_id: str | None = Field(default=None, max_length=200)
    defect_kind: str | None = Field(default=None, max_length=100)
    severity: str = Field(default="normal", max_length=50)


class TrivialCorrectionIn(BaseModel):
    corrected_payload: dict[str, Any]


def _subject(auth: dict) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"},
        )
    return subject


def _service() -> EvidenceFeedbackService:
    root = os.environ.get(
        "CALYX_EVIDENCE_FEEDBACK_ROOT",
        "data/evidence_feedback",
    )
    return EvidenceFeedbackService(FileEvidenceFeedbackRepository(root))


def _translate(exc: Exception) -> None:
    code = str(exc)
    if isinstance(exc, EvidenceFeedbackRepositoryError):
        status = 404 if code in {
            "CASE_NOT_FOUND",
            "OBJECT_VERSION_NOT_FOUND",
        } else 409 if code in {
            "FINGERPRINT_ALREADY_BOUND",
            "OBJECT_VERSION_IMMUTABILITY_VIOLATION",
        } else 422
        raise HTTPException(status_code=status, detail={"code": code}) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail={"code": code}) from exc
    if isinstance(exc, ValueError):
        status = 409 if code in {
            "GOVERNED_REVIEW_REQUIRED",
            "SCIENTIFIC_OBJECT_CANNOT_AUTO_CORRECT",
            "STALE_OBJECT_VERSION",
        } else 422
        raise HTTPException(status_code=status, detail={"code": code}) from exc
    raise exc


@router.post("/objects", status_code=201)
def register_object(payload: EvidenceObjectIn, auth: Auth):
    _subject(auth)
    try:
        return _service().register_object(
            object_id=payload.object_id,
            object_type=payload.object_type,
            payload=payload.payload,
            previous_version_hash=payload.previous_version_hash,
        ).to_dict()
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/cases", status_code=201)
def submit_case(payload: EvidenceFeedbackIn, auth: Auth):
    submitter_id = _subject(auth)
    try:
        result = _service().submit(
            object_id=payload.object_id,
            object_version_hash=payload.object_version_hash,
            object_type=payload.object_type,
            page_context=payload.page_context,
            feedback_class=payload.feedback_class,
            statement=payload.statement,
            proposed_replacement=payload.proposed_replacement,
            citation=payload.citation,
            submitter_id=submitter_id,
            source_partner_id=payload.source_partner_id,
            defect_kind=payload.defect_kind,
            severity=payload.severity,
        )
        return {
            "created": result.created,
            "duplicate_of": result.duplicate_of,
            "case": result.case.to_dict(),
        }
    except Exception as exc:
        _translate(exc)
        raise


@router.get("/cases/{case_id}")
def get_case_status(case_id: str, auth: Auth):
    submitter_id = _subject(auth)
    try:
        return _service().status_for_submitter(
            case_id=case_id,
            submitter_id=submitter_id,
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/cases/{case_id}/accept-trivial")
def accept_trivial_correction(
    case_id: str,
    payload: TrivialCorrectionIn,
    auth: Auth,
):
    reviewer_id = _subject(auth)
    try:
        return _service().accept_trivial_correction(
            case_id=case_id,
            reviewer_id=reviewer_id,
            corrected_payload=payload.corrected_payload,
        ).to_dict()
    except Exception as exc:
        _translate(exc)
        raise
