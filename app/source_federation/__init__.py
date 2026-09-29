"""Deterministic source-federation inventory and queue-bridge helpers."""

from .inventory import (
    AccessState,
    CandidateDisposition,
    FederationCandidate,
    RightsState,
    build_default_candidate_inventory,
    deduplicate_candidates,
)
from .queue_bridge import (
    BridgeSuppression,
    IdempotentSourceTaskQueue,
    SourceChildTask,
    SourceQueueBridgeResult,
    bridge_source_candidates,
    persist_source_candidates,
    source_task_key,
)

__all__ = [
    "AccessState",
    "BridgeSuppression",
    "CandidateDisposition",
    "FederationCandidate",
    "IdempotentSourceTaskQueue",
    "RightsState",
    "SourceChildTask",
    "SourceQueueBridgeResult",
    "bridge_source_candidates",
    "build_default_candidate_inventory",
    "deduplicate_candidates",
    "persist_source_candidates",
    "source_task_key",
]
