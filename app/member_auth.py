"""Read-only member access for product research endpoints.

Owner decision (2026-09-26): "Allow member reads: accept Supabase member sessions on
the product endpoints." Scope is strictly read-only. This module provides:

* ``verify_member_or_owner_read`` -- API key, then owner session, then a verified
  Supabase member bearer. Returns a principal with ``role`` and ``actor`` only.
* ``owner_or_member_read`` -- a method-aware, default-deny router dependency. A
  request is admitted on the member path only when its method is GET/HEAD *and* the
  matched endpoint was explicitly marked with ``@member_readable``. Every other
  request (all writes, and every unmarked GET) requires the owner session / API key
  exactly as ``verify_owner_or_api_key`` does today; a *verified* member reaching one
  of those routes gets 403 ``OWNER_ACCESS_REQUIRED`` (anonymous/invalid stay 401).
* Responses served to members on candidate-knowledge and evidence-aggregation routes
  have caller-supplied locality/prose removed (``app.member_redaction``).

Environment:

* ``OC_MEMBER_READS_ENABLED`` -- default enabled. Any value other than
  ``1/true/yes/on`` (e.g. ``false``) restores owner-only behaviour.
* ``OC_SUPABASE_URL`` / ``OC_SUPABASE_ANON_KEY`` -- Supabase project used to verify
  member sessions; fall back to the University learner variables
  ``OCU_SUPABASE_URL`` / ``OCU_SUPABASE_ANON_KEY`` (same project).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException, Request, Security
from starlette.concurrency import run_in_threadpool

from app.security import (
    OWNER_SESSION_COOKIE,
    _decode_owner_token,
    api_key_header,
    get_api_key,
    verify_owner_or_api_key,
)
from app.university.learner_auth import resolve_supabase_actor

MEMBER_READS_ENV = "OC_MEMBER_READS_ENABLED"
READ_METHODS = frozenset({"GET", "HEAD"})
MEMBER_READABLE_ATTR = "__oc_member_readable__"

MEMBER_TOKEN_CACHE_TTL_SECONDS = 60.0
MEMBER_TOKEN_CACHE_MAX_ENTRIES = 1024

# Owner session tokens are ``<urlsafe-b64 payload>.<64 hex sha256 hmac>``: exactly one
# dot and a lowercase hex signature. Supabase access tokens are three-part JWTs, so
# they never match. A token of owner shape is only ever decoded as an owner token and
# is never forwarded to Supabase, even when it is invalid, expired or revoked.
_OWNER_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]+\.[0-9a-f]{64}$")

F = TypeVar("F", bound=Callable[..., Any])


def member_reads_enabled() -> bool:
    value = os.getenv(MEMBER_READS_ENV)
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def member_supabase_url() -> str | None:
    value = _env_first("OC_SUPABASE_URL", "OCU_SUPABASE_URL")
    return value.rstrip("/") if value else None


def member_supabase_anon_key() -> str | None:
    return _env_first("OC_SUPABASE_ANON_KEY", "OCU_SUPABASE_ANON_KEY")


def member_readable(endpoint: F) -> F:
    """Mark a GET endpoint as readable by a verified member session.

    Apply *below* the ``@router.get`` decorator. The marker has no effect on non-read
    methods: ``owner_or_member_read`` still requires the owner for them.
    """
    setattr(endpoint, MEMBER_READABLE_ATTR, True)
    return endpoint


# --- verified member token cache -------------------------------------------------

_cache_lock = threading.Lock()
_member_cache: OrderedDict[str, tuple[float, dict[str, object]]] = OrderedDict()


def _cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unverified_jwt_exp(token: str) -> float | None:
    """Read ``exp`` from a JWT payload, only ever to *shorten* the cache lifetime."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = payload.get("exp") if isinstance(payload, dict) else None
        return float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None
    except (ValueError, TypeError):
        return None


def _cache_get(token: str) -> dict[str, object] | None:
    key = _cache_key(token)
    now = time.monotonic()
    with _cache_lock:
        entry = _member_cache.get(key)
        if entry is None:
            return None
        expires_at, principal = entry
        if expires_at <= now:
            _member_cache.pop(key, None)
            return None
        return dict(principal)


def _cache_put(token: str, principal: dict[str, object]) -> None:
    ttl = MEMBER_TOKEN_CACHE_TTL_SECONDS
    exp = _unverified_jwt_exp(token)
    if exp is not None:
        ttl = min(ttl, exp - time.time())
    if ttl <= 0:
        return
    key = _cache_key(token)
    now = time.monotonic()
    with _cache_lock:
        _member_cache[key] = (now + ttl, dict(principal))
        _member_cache.move_to_end(key)
        if len(_member_cache) > MEMBER_TOKEN_CACHE_MAX_ENTRIES:
            for stale in [k for k, (expires_at, _) in _member_cache.items() if expires_at <= now]:
                _member_cache.pop(stale, None)
        while len(_member_cache) > MEMBER_TOKEN_CACHE_MAX_ENTRIES:
            _member_cache.popitem(last=False)


def clear_member_token_cache() -> None:
    with _cache_lock:
        _member_cache.clear()


def verify_member_access_token(token: str) -> dict[str, object]:
    """Verify a Supabase member access token (cached for at most 60 seconds).

    Only successful verifications are cached, keyed by sha256(token); the raw token
    is never stored. Configuration is checked on every call, so removing the
    Supabase configuration takes effect immediately.
    """
    base_url = member_supabase_url()
    anon_key = member_supabase_anon_key()
    if base_url and anon_key:
        cached = _cache_get(token)
        if cached is not None:
            return cached
    identity = resolve_supabase_actor(
        token,
        base_url=base_url,
        anon_key=anon_key,
        code_prefix="MEMBER",
        audience="Member",
        auth_type="supabase_member",
        not_configured_message="Member reads are enabled but Supabase member verification is not configured",
    )
    principal: dict[str, object] = {
        "actor": identity["actor"],
        "subject": identity["subject"],
        "auth_type": "supabase_member",
        "role": "member",
    }
    _cache_put(token, principal)
    return principal


# --- dependencies ------------------------------------------------------------------


def _bearer(request: Request) -> tuple[bool, str]:
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    return bool(authorization), (token.strip() if scheme.lower() == "bearer" else "")


def _owner_principal(token: str) -> dict[str, object]:
    return {**_decode_owner_token(token), "role": "owner"}


async def verify_member_or_owner_read(
    request: Request, api_key: str | None = Security(api_key_header)
) -> dict[str, object]:
    """Authenticate a read: API key -> owner session -> Supabase member bearer."""
    if not member_reads_enabled():
        return await verify_owner_or_api_key(request, api_key)

    if api_key:
        expected_key = get_api_key()
        if not expected_key:
            raise HTTPException(status_code=401, detail="API key authentication is not configured")
        if hmac.compare_digest(api_key, expected_key):
            return {"actor": "backend_api_key", "auth_type": "api_key", "role": "api_key"}
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    has_authorization, bearer = _bearer(request)
    cookie = request.cookies.get(OWNER_SESSION_COOKIE)
    if cookie:
        try:
            return _owner_principal(cookie)
        except HTTPException:
            # A stale owner cookie must not mask a member bearer on the same browser,
            # but without one the owner failure is reported exactly as before.
            if not bearer:
                raise

    if bearer:
        if _OWNER_TOKEN_SHAPE.fullmatch(bearer):
            return _owner_principal(bearer)
        return await run_in_threadpool(verify_member_access_token, bearer)

    if has_authorization:
        raise HTTPException(status_code=401, detail="Owner session is required")
    raise HTTPException(status_code=401, detail="Owner session, member session, or API key is required")


OWNER_ACCESS_REQUIRED = {"code": "OWNER_ACCESS_REQUIRED", "message": "This view is limited to owner access"}


def _record(request: Request, principal: dict[str, object]) -> dict[str, object]:
    request.state.oc_principal = principal
    return principal


async def _verified_member_or_none(request: Request, api_key: str | None) -> dict[str, object] | None:
    """Return the member principal when the request carries a VALID member bearer.

    Used only after the owner path has rejected the request. Owner-shaped bearers are
    never forwarded to Supabase. An unverifiable token (invalid, Supabase down or not
    configured) yields ``None`` so the caller keeps the owner path's 401.
    """
    if api_key or not member_reads_enabled():
        return None
    _, bearer = _bearer(request)
    if not bearer or _OWNER_TOKEN_SHAPE.fullmatch(bearer):
        return None
    try:
        principal = await run_in_threadpool(verify_member_access_token, bearer)
    except HTTPException:
        return None
    return principal if principal.get("role") == "member" else None


async def owner_or_member_read(
    request: Request, api_key: str | None = Security(api_key_header)
) -> dict[str, object]:
    """Router-level, default-deny dependency: member path only for marked GET routes.

    A verified member reaching any other route (every write, every unmarked GET) gets
    403 ``OWNER_ACCESS_REQUIRED``. It runs as a router dependency, before path/body
    validation and before any lookup, so the 403 never reveals whether a resource
    exists. Anonymous and invalid-token requests keep the owner path's 401; owner and
    API-key behaviour is unchanged.
    """
    endpoint = request.scope.get("endpoint")
    if request.method.upper() in READ_METHODS and getattr(endpoint, MEMBER_READABLE_ATTR, False):
        return _record(request, await verify_member_or_owner_read(request, api_key))
    try:
        return _record(request, await verify_owner_or_api_key(request, api_key))
    except HTTPException as exc:
        if exc.status_code in {401, 503} and await _verified_member_or_none(request, api_key) is not None:
            raise HTTPException(status_code=403, detail=dict(OWNER_ACCESS_REQUIRED)) from None
        raise
