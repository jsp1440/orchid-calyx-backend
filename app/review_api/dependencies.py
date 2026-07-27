from __future__ import annotations

import os
from functools import lru_cache
from typing import Callable

import psycopg
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from psycopg.rows import dict_row

from app.mission_control_access import (
    AccessPrincipal,
    AuthenticatedIdentity,
    PrincipalResolutionError,
    PrincipalResolver,
)
from app.review_tasks.postgres_repository import PostgresReviewTaskRepository
from app.review_tasks.service import GovernedReviewTaskService
from app.security import OWNER_SESSION_COOKIE, _decode_owner_token, get_api_key

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_principal_resolver = PrincipalResolver()


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL")


def _connection_factory() -> Callable[[], object]:
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is required for persistent review API access")
    return lambda: psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


@lru_cache(maxsize=1)
def persistent_review_service() -> GovernedReviewTaskService:
    repository = PostgresReviewTaskRepository(_connection_factory())
    return GovernedReviewTaskService(repository=repository)


def review_service_dependency() -> GovernedReviewTaskService:
    if _database_url():
        return persistent_review_service()
    if os.getenv("MISSION_CONTROL_REVIEW_ALLOW_MEMORY", "false").lower() in {"1", "true", "yes", "on"}:
        return GovernedReviewTaskService()
    raise HTTPException(
        status_code=503,
        detail={
            "code": "REVIEW_DATABASE_NOT_CONFIGURED",
            "message": "DATABASE_URL must be configured for Mission Control review APIs.",
        },
    )


def _identity_from_owner_session(request: Request) -> AuthenticatedIdentity | None:
    token = request.cookies.get(OWNER_SESSION_COOKIE)
    authorization = request.headers.get("authorization") or ""
    scheme, _, bearer = authorization.partition(" ")
    if not token and scheme.lower() == "bearer":
        token = bearer
    if not token:
        return None
    auth = _decode_owner_token(token)
    return AuthenticatedIdentity(
        subject_id=str(auth["actor"]),
        authenticated=True,
        role_names=("ADMINISTRATOR",),
        metadata={"auth_source": str(auth["auth_type"])},
    )


async def authenticated_principal(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> AccessPrincipal:
    identity = _identity_from_owner_session(request)
    if identity is None and api_key:
        expected = get_api_key()
        if not expected or api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid API key")
        identity = AuthenticatedIdentity(
            subject_id="backend_api_key",
            authenticated=True,
            role_names=("ADMINISTRATOR",),
            metadata={"auth_source": "api_key"},
        )
    if identity is None:
        raise HTTPException(status_code=401, detail="Owner session or API key is required")
    try:
        return _principal_resolver.resolve(identity)
    except PrincipalResolutionError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": exc.code, "details": exc.details},
        ) from exc
