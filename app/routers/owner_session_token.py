from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.routers.owner_operations import allowed_actions
from app.security import (
    OWNER_SESSION_COOKIE,
    owner_cookie_samesite,
    owner_cookie_secure,
    owner_session_ttl_seconds,
    verify_owner_access_code,
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
