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
    """Allow University session creation and learner event mutations.

    This remains disabled unless both the University and explicit write flag are on.
    It does not by itself enable durable persistence, publication, Candidate Knowledge
    writes, or Calyx model calls.
    """
    return university_enabled() and env_bool("OCU_UNIVERSITY_SESSION_WRITES_ENABLED", False)


def learner_auth_enabled() -> bool:
    """Require backend-verifiable learner identity for University session routes."""
    return university_enabled() and env_bool("OCU_UNIVERSITY_LEARNER_AUTH_ENABLED", False)


def learner_supabase_url() -> str | None:
    value = os.getenv("OCU_SUPABASE_URL")
    return value.rstrip("/") if value and value.strip() else None


def learner_supabase_anon_key() -> str | None:
    value = os.getenv("OCU_SUPABASE_ANON_KEY")
    return value.strip() if value and value.strip() else None
