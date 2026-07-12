import os
import hmac
import hashlib
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Optional
from fastapi import Header, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
OWNER_SESSION_COOKIE = "calyx_owner_session"
REVOKED_OWNER_NONCES: set[str] = set()


def get_api_key():
    return os.getenv("CALYX_API_KEY")


def get_owner_access_code() -> str | None:
    return os.getenv("CALYX_OWNER_ACCESS_CODE")


def get_owner_session_secret() -> str | None:
    return os.getenv("CALYX_OWNER_SESSION_SECRET")

def owner_session_ttl_seconds() -> int:
    try: return max(300, min(int(os.getenv("CALYX_OWNER_SESSION_TTL_SECONDS", "3600")), 86400))
    except ValueError: return 3600

def owner_cookie_secure() -> bool:
    value = os.getenv("CALYX_OWNER_COOKIE_SECURE")
    return value.strip().lower() in {"1", "true", "yes", "on"} if value is not None else bool(os.getenv("RENDER"))

def owner_cookie_samesite() -> str:
    value = os.getenv("CALYX_OWNER_COOKIE_SAMESITE", "none" if owner_cookie_secure() else "lax").lower()
    return value if value in {"lax", "strict", "none"} else "lax"


async def verify_api_key(api_key: str = Security(api_key_header)):
    expected_key = get_api_key()
    if not expected_key:
        raise HTTPException(status_code=401, detail="API key authentication is not configured")
    if not api_key or not hmac.compare_digest(api_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    return urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_owner_session_token(owner: str, *, ttl_seconds: int | None = None) -> dict[str, object]:
    secret = get_owner_session_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Owner session signing is not configured")
    now = int(time.time())
    expires_at = now + (ttl_seconds or owner_session_ttl_seconds())
    nonce = secrets.token_urlsafe(12)
    payload = f"{owner}|{now}|{expires_at}|{nonce}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{_b64(payload.encode('utf-8'))}.{signature}"
    return {"token": token, "expires_at": expires_at, "owner": owner}


def verify_owner_access_code(access_code: str, owner: str = "owner") -> dict[str, object]:
    expected = get_owner_access_code()
    if not expected:
        raise HTTPException(status_code=503, detail="Owner access is not configured")
    # compare_digest only supports ASCII strings. Comparing UTF-8 bytes keeps the
    # constant-time comparison while safely handling pasted Unicode characters.
    if not hmac.compare_digest(access_code.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid owner access code")
    return create_owner_session_token(owner)


def _decode_owner_token(token: str) -> dict[str, object]:
    secret = get_owner_session_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Owner session signing is not configured")
    try:
        payload_b64, signature = token.split(".", 1)
        payload = _unb64(payload_b64).decode("utf-8")
        expected_signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("signature")
        owner, issued_at, expires_at, nonce = payload.split("|", 3)
        if int(expires_at) < int(time.time()):
            raise HTTPException(status_code=401, detail="Owner session expired")
        if nonce in REVOKED_OWNER_NONCES:
            raise HTTPException(status_code=401, detail="Owner session ended")
        return {
            "actor": owner,
            "auth_type": "owner_session",
            "issued_at": int(issued_at),
            "expires_at": int(expires_at),
            "nonce": nonce,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid owner session") from exc


async def verify_owner_session(request: Request) -> dict[str, object]:
    token = request.cookies.get(OWNER_SESSION_COOKIE)
    if not token:
        authorization = request.headers.get("authorization") or ""
        scheme, _, bearer = authorization.partition(" ")
        token = bearer if scheme.lower() == "bearer" else ""
    if not token:
        raise HTTPException(status_code=401, detail="Owner session is required")
    return _decode_owner_token(token)


async def verify_owner_or_api_key(request: Request, api_key: str = Security(api_key_header)) -> dict[str, object]:
    expected_key = get_api_key()
    if api_key:
        if not expected_key:
            raise HTTPException(status_code=401, detail="API key authentication is not configured")
        if hmac.compare_digest(api_key, expected_key):
            return {"actor": "backend_api_key", "auth_type": "api_key"}
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    authorization = request.headers.get("authorization") or ""
    if authorization or request.cookies.get(OWNER_SESSION_COOKIE):
        return await verify_owner_session(request)
    raise HTTPException(status_code=401, detail="Owner session or API key is required")


def require_admin(x_orchid_admin_key: Optional[str] = Header(default=None, alias="X-Orchid-Admin-Key")) -> None:
    admin_key = os.getenv("ORCHID_JUDGE_ADMIN_KEY")
    if not admin_key:
        return None
    if x_orchid_admin_key != admin_key:
        raise HTTPException(status_code=401, detail="Invalid admin key.")


def require_judge(x_judge_id: Optional[str] = Header(default=None, alias="X-Judge-Id")) -> str:
    if not x_judge_id:
        raise HTTPException(status_code=401, detail="X-Judge-Id header is required.")
    return x_judge_id
