"""Governed Matrix Identification sessions: owner/API key, plus members for their own.

Release 1 journey 4 (owner decision 2026-09-26): a signed-in member may create a
session and read, answer, rank and explain the sessions THEY created. The session is
bound server-side to the verified member's Supabase subject; another account's
session is reported as not found. Persistence status/preflight stay owner-only.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.matrix_member_access import (
    MEMBER_MAX_OBSERVATIONS_PER_SESSION,
    is_member,
    matrix_member_route,
    owner_or_matrix_member,
)
from app.matrix_member_views import (
    member_evaluation,
    member_observation_source,
    member_session,
    member_session_metadata,
)
from app.security import verify_owner_or_api_key
from runtime.matrix_identification_persistence_preflight import (
    matrix_session_persistence_preflight,
)
from runtime.matrix_identification_session import (
    add_observation,
    create_session,
    evaluate_session,
    get_session,
    persistence_status,
)


class SessionCreateRequest(BaseModel):
    registry_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    metadata: dict[str, Any] | None = None


class SessionObservationRequest(BaseModel):
    character: str = Field(min_length=1, max_length=120)
    value: Any
    certainty: Literal["certain", "probable", "uncertain", "unknown"] = "certain"
    weight: float | None = Field(default=None, ge=0, le=100)
    source: dict[str, Any] | None = None


class SessionEvaluateRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


router = APIRouter(
    prefix="/api/matrix-identification/sessions",
    tags=["matrix-identification-sessions"],
    dependencies=[Depends(owner_or_matrix_member)],
)


def _authenticated_actor(auth: Any) -> str:
    if not isinstance(auth, dict):
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    actor = str(auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    return actor


def _access_actor(auth: Any) -> str | None:
    """Owner sessions are tenant-scoped; API-key callers are trusted system automation."""
    if not isinstance(auth, dict):
        raise HTTPException(status_code=401, detail="authenticated actor unavailable")
    if auth.get("auth_type") == "api_key":
        return None
    return _authenticated_actor(auth)


def _member_session_id(auth: Any, session_id: str) -> None:
    """Members address sessions by UUID only; anything else is simply not found."""
    if not is_member(auth):
        return
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail=f"identification session not found: {session_id}"
        ) from exc


def _service_unavailable(exc: RuntimeError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "MATRIX_SESSION_PERSISTENCE_UNAVAILABLE", "message": str(exc)},
    )


@router.get("/persistence-status")
def get_persistence_status(
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    return persistence_status()


@router.get("/persistence-preflight")
def get_persistence_preflight(
    _: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Read-only inspection of durable-session activation prerequisites."""
    return matrix_session_persistence_preflight()


@router.post("")
@matrix_member_route("session_create")
def create(
    payload: SessionCreateRequest,
    auth: Any = Depends(owner_or_matrix_member),  # noqa: B008
) -> dict[str, Any]:
    member = is_member(auth)
    try:
        record = create_session(
            registry_id=payload.registry_id,
            version=payload.version,
            actor=_authenticated_actor(auth),
            metadata=member_session_metadata(payload.metadata)
            if member
            else payload.metadata,
        )
        return member_session(record) if member else record
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.get("/{session_id}")
@matrix_member_route("read")
def get(
    session_id: str,
    auth: Any = Depends(owner_or_matrix_member),  # noqa: B008
) -> dict[str, Any]:
    _member_session_id(auth, session_id)
    try:
        record = get_session(session_id, access_actor=_access_actor(auth))
        return member_session(record) if is_member(auth) else record
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/{session_id}/observations")
@matrix_member_route("session_write")
def observe(
    session_id: str,
    payload: SessionObservationRequest,
    auth: Any = Depends(owner_or_matrix_member),  # noqa: B008
) -> dict[str, Any]:
    member = is_member(auth)
    _member_session_id(auth, session_id)
    try:
        if member:
            existing = get_session(session_id, access_actor=_access_actor(auth))
            if (
                len(existing.get("observations") or [])
                >= MEMBER_MAX_OBSERVATIONS_PER_SESSION
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "MATRIX_MEMBER_SESSION_OBSERVATION_LIMIT",
                        "message": (
                            "This identification session has reached its observation limit "
                            f"({MEMBER_MAX_OBSERVATIONS_PER_SESSION}). Start a new session."
                        ),
                    },
                )
        record = add_observation(
            session_id,
            character=payload.character,
            value=payload.value,
            certainty=payload.certainty,
            weight=payload.weight,
            source=member_observation_source(payload.source)
            if member
            else payload.source,
            actor=_authenticated_actor(auth),
            access_actor=_access_actor(auth),
        )
        return member_session(record) if member else record
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/{session_id}/evaluate")
@matrix_member_route("session_write")
def evaluate(
    session_id: str,
    payload: SessionEvaluateRequest,
    auth: Any = Depends(owner_or_matrix_member),  # noqa: B008
) -> dict[str, Any]:
    _member_session_id(auth, session_id)
    try:
        evaluation = evaluate_session(
            session_id,
            limit=payload.limit,
            access_actor=_access_actor(auth),
        )
        return member_evaluation(evaluation) if is_member(auth) else evaluation
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc
