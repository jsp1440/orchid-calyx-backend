"""Scientific Kernel runtime orchestration contracts and immutable execution models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID, uuid4

from .exceptions import ScientificObjectValidationError
from .identity import OCID
from .models import ScientificObject


class RuntimeOperation(str, Enum):
    """Canonical operations coordinated by the Scientific Runtime."""

    REGISTER_EVIDENCE = "register_evidence"
    PUBLISH_ASSERTION = "publish_assertion"
    CREATE_RELATIONSHIP = "create_relationship"
    PREPARE_PUBLICATION = "prepare_publication"
    COMMIT_PUBLICATION = "commit_publication"
    PUBLISH_KNOWLEDGE = "publish_knowledge"
    EXECUTE_QUERY = "execute_query"
    PUBLISH_EVENT = "publish_event"


class RuntimeStatus(str, Enum):
    """Lifecycle states for one runtime execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Immutable transaction-scoped context shared by coordinated Kernel services."""

    correlation_id: UUID = field(default_factory=uuid4)
    actor: str | None = None
    publication_ocid: OCID | None = None
    causation_event_ocid: OCID | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        actor = self.actor.strip() if self.actor is not None else None
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ScientificObjectValidationError("runtime started_at must be timezone-aware")
        object.__setattr__(self, "actor", actor or None)
        object.__setattr__(self, "started_at", self.started_at.astimezone(timezone.utc))
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    """Immutable request passed to a Scientific Runtime implementation."""

    operation: RuntimeOperation
    context: RuntimeContext = field(default_factory=RuntimeContext)
    scientific_object: ScientificObject | None = None
    target_ocid: OCID | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scientific_object is None and self.target_ocid is None and not self.parameters:
            raise ScientificObjectValidationError(
                "runtime request requires a scientific object, target OCID, or parameters"
            )
        if self.scientific_object is not None and self.target_ocid == self.scientific_object.ocid:
            raise ScientificObjectValidationError(
                "runtime target_ocid must not duplicate scientific_object.ocid"
            )
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """Immutable outcome of a Scientific Runtime execution."""

    operation: RuntimeOperation
    status: RuntimeStatus
    correlation_id: UUID
    scientific_object: ScientificObject | None = None
    output: Any | None = None
    event_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        completed_at = self.completed_at
        if completed_at is not None:
            if completed_at.tzinfo is None or completed_at.utcoffset() is None:
                raise ScientificObjectValidationError(
                    "runtime completed_at must be timezone-aware"
                )
            completed_at = completed_at.astimezone(timezone.utc)

        error_code = self.error_code.strip() if self.error_code is not None else None
        error_message = self.error_message.strip() if self.error_message is not None else None
        event_ocids = tuple(self.event_ocids)
        if len(set(event_ocids)) != len(event_ocids):
            raise ScientificObjectValidationError("runtime event_ocids must be unique")

        if self.status in {
            RuntimeStatus.SUCCEEDED,
            RuntimeStatus.FAILED,
            RuntimeStatus.CANCELLED,
        } and completed_at is None:
            raise ScientificObjectValidationError(
                f"{self.status.value} runtime results require completed_at"
            )
        if self.status is RuntimeStatus.FAILED:
            if not error_code or not error_message:
                raise ScientificObjectValidationError(
                    "failed runtime results require error_code and error_message"
                )
        elif error_code or error_message:
            raise ScientificObjectValidationError(
                "error_code and error_message are valid only for failed results"
            )

        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "error_code", error_code or None)
        object.__setattr__(self, "error_message", error_message or None)
        object.__setattr__(self, "event_ocids", event_ocids)

    @property
    def is_terminal(self) -> bool:
        """Return whether execution has reached a terminal state."""

        return self.status in {
            RuntimeStatus.SUCCEEDED,
            RuntimeStatus.FAILED,
            RuntimeStatus.CANCELLED,
        }
