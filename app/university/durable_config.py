from __future__ import annotations

import os
import re

from .config import env_bool, learner_auth_enabled, session_writes_enabled

EVIDENCE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def valid_release_evidence_id(value: str | None) -> bool:
    return bool(value and EVIDENCE_ID_PATTERN.fullmatch(value.strip()))


def durable_sessions_enabled() -> bool:
    """Return True only when every post-cutover durability gate is explicit.

    Durable learner writes require both cryptographically bound release evidence and
    backend-verifiable learner identity. A signed-in learner remains distinct from a
    qualified Mission Control scientific reviewer.
    """
    return (
        session_writes_enabled()
        and learner_auth_enabled()
        and env_bool("OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED", False)
        and env_bool("OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED", False)
        and valid_release_evidence_id(os.getenv("OCU_UNIVERSITY_RELEASE_EVIDENCE_ID"))
    )


def durable_gate_state() -> dict[str, object]:
    evidence_id = os.getenv("OCU_UNIVERSITY_RELEASE_EVIDENCE_ID", "").strip()
    state = {
        "session_writes_enabled": session_writes_enabled(),
        "learner_auth_enabled": learner_auth_enabled(),
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
            "learner_auth_enabled",
            "durable_flag_enabled",
            "read_only_release_verified",
            "release_evidence_valid",
        )
    )
    return state
