from __future__ import annotations

from uuid import UUID

import requests
from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.security import verify_owner_or_api_key

from .config import (
    learner_auth_enabled,
    learner_supabase_anon_key,
    learner_supabase_url,
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _stable_actor(user_id: object) -> str:
    try:
        canonical = str(UUID(str(user_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_LEARNER_IDENTITY", "message": "Learner identity has no valid stable subject"},
        ) from exc
    return f"supabase:{canonical}"


def verify_supabase_access_token(token: str) -> dict[str, object]:
    """Resolve a Supabase access token through the configured Auth user endpoint.

    Tokens, email addresses, and profile metadata are intentionally not returned to
    University services. Only a stable UUID-derived actor is exposed.
    """
    base_url = learner_supabase_url()
    anon_key = learner_supabase_anon_key()
    if not base_url or not anon_key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "LEARNER_AUTH_NOT_CONFIGURED",
                "message": "University learner authentication is enabled but Supabase verification is not configured",
            },
        )
    try:
        response = requests.get(
            f"{base_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": anon_key,
                "Accept": "application/json",
            },
            timeout=5,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "LEARNER_AUTH_UNAVAILABLE",
                "message": "Learner identity verification is temporarily unavailable",
            },
        ) from exc

    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_LEARNER_TOKEN", "message": "Learner session is invalid or expired"},
        )
    if not response.ok:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "LEARNER_AUTH_UNAVAILABLE",
                "message": "Learner identity verifier returned an unexpected response",
            },
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "LEARNER_AUTH_INVALID_RESPONSE", "message": "Learner identity verifier returned invalid data"},
        ) from exc
    actor = _stable_actor(payload.get("id") if isinstance(payload, dict) else None)
    return {"actor": actor, "subject": actor, "auth_type": "university_learner"}


async def verify_university_actor(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> dict[str, object]:
    """Authenticate a University session actor without conflating learner and reviewer roles.

    Before learner authentication is explicitly enabled, the existing owner/API-key
    prototype contract is preserved. Once enabled, learner session routes accept only
    a verified Supabase bearer identity. Reviewer authorization remains a separate
    Mission Control principal dependency.
    """
    if not learner_auth_enabled():
        return await verify_owner_or_api_key(request, api_key)

    token = _bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"code": "LEARNER_SESSION_REQUIRED", "message": "A signed-in learner session is required"},
        )
    return verify_supabase_access_token(token)
