from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GraphOperationType(StrEnum):
    CREATE_NODE = "CREATE_NODE"
    CREATE_EDGE = "CREATE_EDGE"
    ADD_ASSERTION_SUPPORT = "ADD_ASSERTION_SUPPORT"
    ADD_CONFLICTING_EVIDENCE = "ADD_CONFLICTING_EVIDENCE"
    UPDATE_PUBLICATION_STATUS = "UPDATE_PUBLICATION_STATUS"
    NO_OP_DUPLICATE = "NO_OP_DUPLICATE"


@dataclass(frozen=True)
class GraphOperation:
    order: int
    operation_type: GraphOperationType
    object_key: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.order < 0 or not self.object_key.strip() or not self.payload:
            raise ValueError("INVALID_GRAPH_OPERATION")


@dataclass(frozen=True)
class PublicationExecutionRequest:
    publication_id: int
    publication_version: int
    service_identity: str
    correlation_id: str

    def __post_init__(self) -> None:
        if min(self.publication_id, self.publication_version) <= 0:
            raise ValueError("INVALID_PUBLICATION_REFERENCE")
        if not self.service_identity.strip() or not self.correlation_id.strip():
            raise ValueError("INCOMPLETE_EXECUTION_IDENTITY")
