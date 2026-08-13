"""Owner-gated API for governed Matrix Identification sessions."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
def create(
    payload: SessionCreateRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return create_session(
            registry_id=payload.registry_id,
            version=payload.version,
            actor=_authenticated_actor(auth),
            metadata=payload.metadata,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.get("/{session_id}")
def get(
    session_id: str,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return get_session(session_id, access_actor=_access_actor(auth))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/{session_id}/observations")
def observe(
    session_id: str,
    payload: SessionObservationRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return add_observation(
            session_id,
            character=payload.character,
            value=payload.value,
            certainty=payload.certainty,
            weight=payload.weight,
            source=payload.source,
            actor=_authenticated_actor(auth),
            access_actor=_access_actor(auth),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@router.post("/{session_id}/evaluate")
def evaluate(
    session_id: str,
    payload: SessionEvaluateRequest,
    auth: Any = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    try:
        return evaluate_session(
            session_id,
            limit=payload.limit,
            access_actor=_access_actor(auth),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc
