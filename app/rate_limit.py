"""A bounded, in-process brake on anonymous public writes.

Public intake routes (newsletter subscribe/unsubscribe, contact, community
observation submission) accept writes from anyone. Without a brake, one
client can grow the record store without limit. This dependency counts
writes per client and per route family in a sliding window and answers 429
with ``Retry-After`` once the allowance is spent.

What it is: a nuisance brake that is honest about its scope. It is
per-process (each worker keeps its own window), keyed on the client address
the deployment reports, and configurable through the environment.

What it is not: a security boundary. ``X-Forwarded-For`` is taken at face
value because the deployment sits behind a proxy that sets it; a client that
can spoof that header can spread its writes across keys. Authentication and
validation remain the real controls; this only slows abuse of the public
surfaces.

Configuration (environment):

* ``PUBLIC_WRITE_RATE_LIMIT`` — writes allowed per window per client per route
  family (default 20). ``0`` disables the brake.
* ``PUBLIC_WRITE_RATE_WINDOW_SECONDS`` — window length (default 600).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

DEFAULT_LIMIT = 20
DEFAULT_WINDOW_SECONDS = 600
MAX_TRACKED_CLIENTS = 10_000


def configured_limit() -> int:
    raw = os.getenv("PUBLIC_WRITE_RATE_LIMIT", "").strip()
    if not raw:
        return DEFAULT_LIMIT
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_LIMIT


def configured_window_seconds() -> int:
    raw = os.getenv("PUBLIC_WRITE_RATE_WINDOW_SECONDS", "").strip()
    if not raw:
        return DEFAULT_WINDOW_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_WINDOW_SECONDS


def client_key(request: Request) -> str:
    """The client address the deployment reports: first ``X-Forwarded-For`` hop, else the socket peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@dataclass
class SlidingWindowLimiter:
    """Counts events per key in a sliding window. Thread-safe, bounded memory."""

    clock: Callable[[], float] = time.monotonic
    _events: dict[str, deque[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Record one event for ``key``. Returns ``(allowed, retry_after_seconds)``."""
        if limit <= 0:
            return True, 0
        now = self.clock()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= MAX_TRACKED_CLIENTS:
                    self._evict(cutoff)
                events = deque()
                self._events[key] = events
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now) + 1)
                return False, retry_after
            events.append(now)
            return True, 0

    def _evict(self, cutoff: float) -> None:
        stale = [key for key, events in self._events.items() if not events or events[-1] <= cutoff]
        for key in stale:
            del self._events[key]
        if len(self._events) >= MAX_TRACKED_CLIENTS:
            # Still full of active clients: drop the oldest-touched half rather than grow without bound.
            ordered = sorted(self._events.items(), key=lambda item: item[1][-1] if item[1] else 0.0)
            for key, _ in ordered[: len(ordered) // 2]:
                del self._events[key]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


LIMITER = SlidingWindowLimiter()


def public_write_rate_limit(family: str) -> Callable[[Request], None]:
    """Dependency factory: one allowance per client per ``family`` (e.g. ``"constituent"``)."""

    def dependency(request: Request) -> None:
        limit = configured_limit()
        if limit <= 0:
            return
        allowed, retry_after = LIMITER.check(
            f"{family}:{client_key(request)}", limit=limit, window_seconds=configured_window_seconds()
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many submissions from this client. Please wait and try again.",
                headers={"Retry-After": str(retry_after)},
            )

    dependency.__name__ = f"public_write_rate_limit_{family}"
    return dependency
