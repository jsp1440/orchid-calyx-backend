import os
from typing import Optional
from fastapi import Header, HTTPException, Security, Request
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key():
    return os.getenv("CALYX_API_KEY")


async def verify_api_key(api_key: str = Security(api_key_header)):
    expected_key = get_api_key()
    if expected_key is None:
        return None
    if api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


def require_admin(x_orchid_admin_key: Optional[str] = Header(default=None, alias="X-Orchid-Admin-Key")) -> None:
    admin_key = os.getenv("ORCHID_JUDGE_ADMIN_KEY")
    if not admin_key:
        return None
    if x_orchid_admin_key != admin_key:
        raise HTTPException(status_code=401, detail="Invalid admin key.")
