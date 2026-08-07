from __future__ import annotations

from .config import session_writes_enabled, university_enabled

RELEASE_CONTRACT_VERSION = "OCU-RELEASE-001"
CONTENT_CONTRACT_VERSION = "OCU-SCI-003"


def release_readiness() -> dict[str, object]:
    """Return non-sensitive deployment facts for smoke tests and operators."""

    enabled = university_enabled()
    writes_enabled = session_writes_enabled()
    return {
        "release_contract": RELEASE_CONTRACT_VERSION,
        "content_contract": CONTENT_CONTRACT_VERSION,
        "university_enabled": enabled,
        "read_only_ready": enabled and not writes_enabled,
        "session_writes_enabled": writes_enabled,
        "persistence": "process_local_memory",
        "publication_enabled": False,
        "candidate_knowledge_writes_enabled": False,
        "calyx_model_calls_enabled": False,
        "human_review_required": True,
        "required_read_only_configuration": {
            "OCU_UNIVERSITY_ENABLED": True,
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": False,
        },
    }
