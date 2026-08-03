from __future__ import annotations

import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def university_enabled() -> bool:
    """Enable the read-only University catalog and prototype session endpoints."""
    return env_bool("OCU_UNIVERSITY_ENABLED", False)


def session_writes_enabled() -> bool:
    """Allow process-local prototype session creation and event appends.

    This remains disabled unless both the University and explicit write flag are on.
    It does not enable database persistence, publication, Candidate Knowledge writes,
    or Calyx model calls.
    """
    return university_enabled() and env_bool("OCU_UNIVERSITY_SESSION_WRITES_ENABLED", False)
