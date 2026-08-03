from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.routers.owner_operations import allowed_actions
from app.security import (
    OWNER_SESSION_COOKIE,
    owner_cookie_samesite,
    owner_cookie_secure,
    owner_session_ttl_seconds,
    verify_owner_access_code,
    verify_owner_session,
)

router = APIRouter(prefix="/api/mission-control/owner", tags=["owner-operations"])


class OwnerTokenLoginRequest(BaseModel):
    access_code: str
    owner: str = "owner"


@router.post("/session-token")
def create_token_session(request: OwnerTokenLoginRequest, response: Response) -> dict[str, Any]:
    """Create an owner session with a bearer fallback for browsers blocking cross-site cookies."""
    session = verify_owner_access_code(request.access_code, request.owner)
    token = str(session["token"])
    response.set_cookie(
        OWNER_SESSION_COOKIE,
        token,
        max_age=owner_session_ttl_seconds(),
        expires=owner_session_ttl_seconds(),
        httponly=True,
        secure=owner_cookie_secure(),
        samesite=owner_cookie_samesite(),
        path="/api/",
    )
    return {
        "authenticated": True,
        "status": "authenticated",
        "owner": session["owner"],
        "expires_at": session["expires_at"],
        "token": token,
        "allowedActions": allowed_actions(True),
        "credential_transport": "httponly_cookie_or_bearer",
    }


@router.post("/session-token/refresh")
async def refresh_token_session(
    request: Request,
    session: dict[str, object] = Depends(verify_owner_session),
) -> dict[str, Any]:
    """Return the already-authenticated cookie token as a same-tab bearer fallback.

    This endpoint never accepts an access code and never creates a second owner
    identity. It only converts a currently valid signed HttpOnly cookie session
    into the bearer transport required by browsers that inconsistently send
    cross-site cookies on protected POST or multipart requests.
    """
    token = request.cookies.get(OWNER_SESSION_COOKIE)
    if not token:
        authorization = request.headers.get("authorization") or ""
        scheme, _, bearer = authorization.partition(" ")
        token = bearer if scheme.lower() == "bearer" else ""
    return {
        "authenticated": True,
        "status": "authenticated",
        "owner": session["actor"],
        "expires_at": session["expires_at"],
        "token": token,
        "allowedActions": allowed_actions(True),
        "credential_transport": "existing_owner_session_bearer",
    }
