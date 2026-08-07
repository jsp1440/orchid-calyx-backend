from __future__ import annotations

import os

from .config import env_bool, session_writes_enabled


def durable_sessions_enabled() -> bool:
    """Return True only when every post-cutover durability gate is explicit.

    OCU-SCI-008 deliberately does not wire this function into API routes. It exists
    so a later activation build has one fail-closed policy boundary rather than
    scattering environment checks across repositories and routers.
    """
    return (
        session_writes_enabled()
        and env_bool("OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED", False)
        and env_bool("OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED", False)
        and bool(os.getenv("OCU_UNIVERSITY_RELEASE_EVIDENCE_ID", "").strip())
    )


def durable_gate_state() -> dict[str, object]:
    evidence_id = os.getenv("OCU_UNIVERSITY_RELEASE_EVIDENCE_ID", "").strip()
    state = {
        "session_writes_enabled": session_writes_enabled(),
        "durable_flag_enabled": env_bool("OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED", False),
        "read_only_release_verified": env_bool("OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED", False),
        "release_evidence_present": bool(evidence_id),
        "release_evidence_id": evidence_id or None,
    }
    state["durable_sessions_enabled"] = all(
        bool(state[key])
        for key in (
            "session_writes_enabled",
            "durable_flag_enabled",
            "read_only_release_verified",
            "release_evidence_present",
        )
    )
    return state
