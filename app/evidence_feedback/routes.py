"""Authenticated HTTP surface for contextual evidence feedback."""

from __future__ import annotations

import logging
import os
from threading import Lock
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.persistence.state_repository import configured_database_url
from app.security import verify_owner_or_api_key

from .models import FeedbackClass, ObjectType
from .repository import (
    EvidenceFeedbackRepository,
    EvidenceFeedbackRepositoryError,
    EvidenceFeedbackStoreUnavailable,
    FileEvidenceFeedbackRepository,
)
from .service import EvidenceFeedbackService

if TYPE_CHECKING:
    from .postgres_repository import PostgresEvidenceFeedbackRepository

logger = logging.getLogger(__name__)

# Every product router is mounted under ``/api``. The owner session cookie is
# scoped to ``path=/api/``, so a browser only sends it to routes below that
# prefix; the frontend client (src/lib/evidenceFeedback.ts) calls
# ``/api/evidence-feedback``. Auth stays owner session or backend API key.
EVIDENCE_FEEDBACK_PREFIX = "/api/evidence-feedback"
router = APIRouter(prefix=EVIDENCE_FEEDBACK_PREFIX, tags=["evidence-feedback"])
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


FEEDBACK_ROOT_ENV = "CALYX_EVIDENCE_FEEDBACK_ROOT"
DEFAULT_FEEDBACK_ROOT = "data/evidence_feedback"
NON_DURABLE_WARNING = (
    "Evidence feedback is NOT durable: no DATABASE_URL and no "
    f"{FEEDBACK_ROOT_ENV} are configured, so corrections are written under "
    f"'{DEFAULT_FEEDBACK_ROOT}' on this instance's local filesystem and will be "
    "lost when it restarts or redeploys. Configure DATABASE_URL (preferred) or "
    f"point {FEEDBACK_ROOT_ENV} at persistent storage."
)

# One PostgreSQL repository per database URL, built lazily. A failed build is
# not cached, so the next request retries instead of staying unavailable.
_POSTGRES_REPOSITORIES: dict[str, PostgresEvidenceFeedbackRepository] = {}
_POSTGRES_LOCK = Lock()


def _production_like() -> bool:
    env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    render = (os.getenv("RENDER") or "").strip().lower()
    return env in {"prod", "production"} or render in {"1", "true", "yes", "on"}


def non_durable_store_warning() -> str | None:
    """The warning to log when production feedback would be non-durable."""

    if configured_database_url() or (os.getenv(FEEDBACK_ROOT_ENV) or "").strip():
        return None
    return NON_DURABLE_WARNING if _production_like() else None


def warn_if_non_durable() -> str | None:
    message = non_durable_store_warning()
    if message:
        logger.warning(message)
    return message


def reset_repository_cache() -> None:
    """Forget built PostgreSQL repositories (a fresh process after restart)."""

    with _POSTGRES_LOCK:
        _POSTGRES_REPOSITORIES.clear()


def _postgres_repository(database_url: str) -> PostgresEvidenceFeedbackRepository:
    with _POSTGRES_LOCK:
        repository = _POSTGRES_REPOSITORIES.get(database_url)
        if repository is None:
            from .postgres_repository import PostgresEvidenceFeedbackRepository

            repository = PostgresEvidenceFeedbackRepository(database_url)
            _POSTGRES_REPOSITORIES[database_url] = repository
        return repository


def _repository() -> EvidenceFeedbackRepository:
    """The durable database store when configured, else the file store.

    A configured but unreachable database raises
    ``EvidenceFeedbackStoreUnavailable`` (HTTP 503); it never falls back to
    files, which would split feedback between two stores.
    """

    database_url = configured_database_url()
    if database_url:
        return _postgres_repository(database_url)
    root = os.environ.get(FEEDBACK_ROOT_ENV, DEFAULT_FEEDBACK_ROOT)
    return FileEvidenceFeedbackRepository(root)


def _service() -> EvidenceFeedbackService:
    return EvidenceFeedbackService(_repository())


warn_if_non_durable()


def _translate(exc: Exception) -> None:
    code = str(exc)
    if isinstance(exc, EvidenceFeedbackStoreUnavailable):
        raise HTTPException(status_code=503, detail={"code": code}) from exc
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
