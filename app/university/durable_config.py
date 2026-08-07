from __future__ import annotations

import os
import re

from .config import env_bool, session_writes_enabled

EVIDENCE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def valid_release_evidence_id(value: str | None) -> bool:
    return bool(value and EVIDENCE_ID_PATTERN.fullmatch(value.strip()))


def durable_sessions_enabled() -> bool:
    """Return True only when every post-cutover durability gate is explicit.

    OCU-SCI-008A binds activation to a cryptographic identifier generated from a
    passing OCU-SCI-007 production evidence artifact. The repository is still not
    wired into API routes by this build.
    """
    return (
        session_writes_enabled()
        and env_bool("OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED", False)
        and env_bool("OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED", False)
        and valid_release_evidence_id(os.getenv("OCU_UNIVERSITY_RELEASE_EVIDENCE_ID"))
    )


def durable_gate_state() -> dict[str, object]:
    evidence_id = os.getenv("OCU_UNIVERSITY_RELEASE_EVIDENCE_ID", "").strip()
    state = {
        "session_writes_enabled": session_writes_enabled(),
        "durable_flag_enabled": env_bool("OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED", False),
        "read_only_release_verified": env_bool("OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED", False),
        "release_evidence_present": bool(evidence_id),
        "release_evidence_valid": valid_release_evidence_id(evidence_id),
        "release_evidence_id": evidence_id or None,
    }
    state["durable_sessions_enabled"] = all(
        bool(state[key])
        for key in (
            "session_writes_enabled",
            "durable_flag_enabled",
            "read_only_release_verified",
            "release_evidence_valid",
        )
    )
    return state
