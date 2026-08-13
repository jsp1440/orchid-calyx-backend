"""Owner-gated reproducible Matrix Identification report routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.matrix_identification_report import (
    finalize_report,
    get_report,
    list_reports,
)

router = APIRouter(
    prefix="/api/matrix-identification/sessions",
    tags=["matrix-identification-reports"],
)


class FinalizeReportRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


def _access_actor(auth: Any) -> str | None:
    if not isinstance(auth, dict):
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    if auth.get("auth_type") == "api_key":
        return None
    actor = str(auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    return actor


def _raise(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(
            status_code=503,
            detail={"code": "MATRIX_SESSION_PERSISTENCE_UNAVAILABLE", "message": str(exc)},
        ) from exc
    raise exc


@router.post("/{session_id}/reports")
def create_report(
    session_id: str,
    payload: FinalizeReportRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return finalize_report(
            session_id,
            access_actor=_access_actor(auth),
            limit=payload.limit,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        _raise(exc)
        raise AssertionError("unreachable")


@router.get("/{session_id}/reports")
def reports(
    session_id: str,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return list_reports(session_id, access_actor=_access_actor(auth))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        _raise(exc)
        raise AssertionError("unreachable")


@router.get("/{session_id}/reports/{report_id}")
def report(
    session_id: str,
    report_id: str,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return get_report(session_id, report_id, access_actor=_access_actor(auth))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        _raise(exc)
        raise AssertionError("unreachable")
