"""Signed-in member access to Matrix identification (Release 1 journey 4).

Owner decisions (2026-09-26): Matrix identification is available to signed-in
members ("any signed-in account counts as a member"); a session is private to the
account that created it; candidate evidence internals and owner tools stay owner-only.

This module provides one router-level, default-deny dependency,
``owner_or_matrix_member``, applied to every ``/api/matrix-identification`` router:

* An endpoint explicitly marked ``@matrix_member_route`` admits the owner session,
  the API key, or a verified Supabase member bearer (``verify_member_or_owner_read``
  from ``app.member_auth``: owner-shaped tokens are never sent to Supabase, member
  verification is cached for at most 60 seconds, Supabase down -> 503).
* Every other endpoint on those routers requires the owner session / API key exactly
  as ``verify_owner_or_api_key`` does. A *verified* member gets 403
  ``OWNER_ACCESS_REQUIRED`` before path/body validation and before any lookup, so the
  refusal never discloses whether a resource exists. Anonymous and unverifiable
  tokens keep 401.

For member principals only, the dependency also bounds the request body and applies
per-account, in-process rate limits (session creation per hour; session writes per
minute). Owner and API-key requests are never limited here.

Session tenancy is enforced by the existing session runtime: the session's ``actor``
is taken from the verified principal (``supabase:<uuid>`` for members), never from
the request body, and a session read with a different ``access_actor`` is reported
as not found.

Environment:

* ``OC_MEMBER_READS_ENABLED`` -- the master member switch from ``app.member_auth``.
  When it is off, members get no Matrix access either.
* ``OC_MEMBER_MATRIX_IDENTIFICATION_ENABLED`` -- default enabled (the owner decision
  opens Matrix identification to members). Any value other than ``1/true/yes/on``
  restores owner-only Matrix identification.
* ``OC_MEMBER_MATRIX_SESSIONS_PER_HOUR`` (default 30) and
  ``OC_MEMBER_MATRIX_WRITES_PER_MINUTE`` (default 120) -- per-account limits.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from fastapi import HTTPException, Request, Security

from app.member_auth import (
    OWNER_ACCESS_REQUIRED,
    _record,
    _verified_member_or_none,
    member_reads_enabled,
    verify_member_or_owner_read,
)
from app.security import api_key_header, verify_owner_or_api_key

MATRIX_MEMBER_ENV = "OC_MEMBER_MATRIX_IDENTIFICATION_ENABLED"
SESSIONS_PER_HOUR_ENV = "OC_MEMBER_MATRIX_SESSIONS_PER_HOUR"
WRITES_PER_MINUTE_ENV = "OC_MEMBER_MATRIX_WRITES_PER_MINUTE"
MATRIX_MEMBER_ATTR = "__oc_matrix_member_route__"

DEFAULT_SESSIONS_PER_HOUR = 30
DEFAULT_WRITES_PER_MINUTE = 120
MEMBER_MAX_BODY_BYTES = 16 * 1024
MEMBER_MAX_OBSERVATIONS_PER_SESSION = 200

Bucket = Literal["read", "session_create", "session_write"]
F = TypeVar("F", bound=Callable[..., Any])


def matrix_members_enabled() -> bool:
    if not member_reads_enabled():
        return False
    value = os.getenv(MATRIX_MEMBER_ENV)
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


def matrix_member_route(bucket: Bucket) -> Callable[[F], F]:
    """Mark an endpoint as open to a verified member for their OWN sessions.

    ``bucket`` selects the member rate limit: ``read`` (none), ``session_create`` or
    ``session_write``. Apply *below* the ``@router.<method>`` decorator.
    """

    def mark(endpoint: F) -> F:
        setattr(endpoint, MATRIX_MEMBER_ATTR, bucket)
        return endpoint

    return mark


def is_member(principal: Any) -> bool:
    return isinstance(principal, dict) and principal.get("role") == "member"


# --- per-account sliding-window limiter -------------------------------------------


class _SlidingWindowLimiter:
    """Process-local limiter keyed by sha256(bucket, actor); bounded key count."""

    def __init__(self, max_keys: int = 4096) -> None:
        self._lock = threading.Lock()
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._max_keys = max_keys

    def hit(
        self, bucket: str, actor: str, *, limit: int, window: float
    ) -> float | None:
        """Record one hit; return seconds to wait when the limit is exceeded."""
        key = hashlib.sha256(f"{bucket}\0{actor}".encode()).hexdigest()
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            self._hits.move_to_end(key)
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1.0, hits[0] + window - now)
            hits.append(now)
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
            return None

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = _SlidingWindowLimiter()


def clear_member_matrix_limits() -> None:
    _limiter.clear()


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


_LIMITS: dict[str, tuple[str, int, float]] = {
    "session_create": (SESSIONS_PER_HOUR_ENV, DEFAULT_SESSIONS_PER_HOUR, 3600.0),
    "session_write": (WRITES_PER_MINUTE_ENV, DEFAULT_WRITES_PER_MINUTE, 60.0),
}


def _enforce_rate_limit(bucket: str, actor: str) -> None:
    config = _LIMITS.get(bucket)
    if config is None:
        return
    env_name, default, window = config
    retry_after = _limiter.hit(
        bucket, actor, limit=_positive_int_env(env_name, default), window=window
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "MATRIX_MEMBER_RATE_LIMITED",
                "message": "Too many Matrix identification requests for this account. Try again later.",
            },
            headers={"Retry-After": str(int(retry_after + 0.999))},
        )


async def _enforce_body_bound(request: Request) -> None:
    declared = request.headers.get("content-length")
    too_large = False
    if declared is not None:
        try:
            too_large = int(declared) > MEMBER_MAX_BODY_BYTES
        except ValueError:
            too_large = True
    if not too_large:
        too_large = len(await request.body()) > MEMBER_MAX_BODY_BYTES
    if too_large:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "MATRIX_MEMBER_PAYLOAD_TOO_LARGE",
                "message": f"Matrix identification requests are limited to {MEMBER_MAX_BODY_BYTES} bytes.",
            },
        )


# --- dependency ----------------------------------------------------------------------


async def owner_or_matrix_member(
    request: Request, api_key: str | None = Security(api_key_header)
) -> dict[str, object]:
    """Router-level, default-deny gate for ``/api/matrix-identification`` routers."""
    endpoint = request.scope.get("endpoint")
    bucket = getattr(endpoint, MATRIX_MEMBER_ATTR, None)
    if bucket and matrix_members_enabled():
        principal = await verify_member_or_owner_read(request, api_key)
        if is_member(principal):
            if request.method.upper() not in {"GET", "HEAD"}:
                await _enforce_body_bound(request)
            _enforce_rate_limit(str(bucket), str(principal.get("actor") or ""))
        return _record(request, principal)
    try:
        return _record(request, await verify_owner_or_api_key(request, api_key))
    except HTTPException as exc:
        if (
            exc.status_code in {401, 503}
            and await _verified_member_or_none(request, api_key) is not None
        ):
            raise HTTPException(
                status_code=403, detail=dict(OWNER_ACCESS_REQUIRED)
            ) from None
        raise
