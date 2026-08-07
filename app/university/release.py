from __future__ import annotations

from .config import learner_auth_enabled, session_writes_enabled, university_enabled
from .durable_config import durable_gate_state, durable_sessions_enabled

RELEASE_CONTRACT_VERSION = "OCU-RELEASE-003"
CONTENT_CONTRACT_VERSION = "OCU-SCI-003"


def release_readiness() -> dict[str, object]:
    """Return non-sensitive deployment facts for smoke tests and operators.

    Read-only release remains valid with learner authentication disabled. Durable
    learner writes require backend-verifiable learner authentication in addition to
    the OCU-SCI-007/008A release-evidence gate.
    """

    enabled = university_enabled()
    writes_enabled = session_writes_enabled()
    learner_auth = learner_auth_enabled()
    durable_enabled = durable_sessions_enabled()
    return {
        "release_contract": RELEASE_CONTRACT_VERSION,
        "content_contract": CONTENT_CONTRACT_VERSION,
        "university_enabled": enabled,
        "read_only_ready": enabled and not writes_enabled,
        "session_writes_enabled": writes_enabled,
        "learner_auth_enabled": learner_auth,
        "persistence": "postgres_durable" if durable_enabled else "process_local_memory",
        "durable_sessions_enabled": durable_enabled,
        "durable_gate": durable_gate_state(),
        "publication_enabled": False,
        "candidate_knowledge_writes_enabled": False,
        "calyx_model_calls_enabled": False,
        "human_review_required": True,
        "required_read_only_configuration": {
            "OCU_UNIVERSITY_ENABLED": True,
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": False,
        },
        "required_durable_identity_configuration": {
            "OCU_UNIVERSITY_LEARNER_AUTH_ENABLED": True,
        },
    }
