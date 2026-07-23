"""Abstract service contracts for future Scientific Kernel engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Iterable

from .events import EventType, ScientificEvent
from .identity import OCID
from .models import ScientificObject
from .queries import QueryPage, ScientificQuery
from .runtime import RuntimeRequest, RuntimeResult


class EvidenceService(ABC):
    """Contract for immutable evidence registration and retrieval."""

    @abstractmethod
    def register(self, evidence: ScientificObject) -> ScientificObject:
        raise NotImplementedError

    @abstractmethod
    def get(self, ocid: OCID) -> ScientificObject | None:
        raise NotImplementedError


class AssertionService(ABC):
    """Contract for evidence-backed assertion lifecycle operations."""

    @abstractmethod
    def publish(self, assertion: ScientificObject) -> ScientificObject:
        raise NotImplementedError

    @abstractmethod
    def list_for_subject(self, subject_ocid: OCID) -> Iterable[ScientificObject]:
        raise NotImplementedError


class RelationshipService(ABC):
    """Contract for durable first-class relationships and graph traversal."""

    @abstractmethod
    def create(self, relationship: ScientificObject) -> ScientificObject:
        raise NotImplementedError

    @abstractmethod
    def get(self, ocid: OCID) -> ScientificObject | None:
        raise NotImplementedError

    @abstractmethod
    def list_for_object(self, object_ocid: OCID) -> Iterable[ScientificObject]:
        raise NotImplementedError

    @abstractmethod
    def traverse(
        self,
        origin_ocid: OCID,
        *,
        max_depth: int = 1,
    ) -> Iterable[ScientificObject]:
        raise NotImplementedError


class PublicationService(ABC):
    """Contract for preparing and atomically committing scientific publications."""

    @abstractmethod
    def prepare(self, publication: ScientificObject) -> ScientificObject:
        raise NotImplementedError

    @abstractmethod
    def commit(self, publication_ocid: OCID) -> ScientificObject:
        raise NotImplementedError

    @abstractmethod
    def reject(self, publication_ocid: OCID, *, reason: str) -> ScientificObject:
        raise NotImplementedError

    @abstractmethod
    def get(self, publication_ocid: OCID) -> ScientificObject | None:
        raise NotImplementedError

    @abstractmethod
    def list_for_object(self, object_ocid: OCID) -> Iterable[ScientificObject]:
        raise NotImplementedError


class ScientificQueryService(ABC):
    """Contract for bounded, implementation-neutral scientific object queries."""

    @abstractmethod
    def execute(self, query: ScientificQuery) -> QueryPage:
        raise NotImplementedError

    @abstractmethod
    def count(self, query: ScientificQuery) -> int:
        raise NotImplementedError

    @abstractmethod
    def get(self, ocid: OCID) -> ScientificObject | None:
        raise NotImplementedError


class KnowledgeObjectService(ABC):
    """Contract for publishing and retrieving curated knowledge syntheses."""

    @abstractmethod
    def publish(self, knowledge_object: ScientificObject) -> ScientificObject:
        raise NotImplementedError

    @abstractmethod
    def get(self, knowledge_ocid: OCID) -> ScientificObject | None:
        raise NotImplementedError

    @abstractmethod
    def list_for_subject(self, subject_ocid: OCID) -> Iterable[ScientificObject]:
        raise NotImplementedError

    @abstractmethod
    def list_supporting_object(self, object_ocid: OCID) -> Iterable[ScientificObject]:
        raise NotImplementedError


EventHandler = Callable[[ScientificEvent], None]


class ScientificEventBus(ABC):
    """Contract for durable publication and subscription of scientific events."""

    @abstractmethod
    def publish(self, event: ScientificEvent) -> ScientificEvent:
        raise NotImplementedError

    @abstractmethod
    def get(self, event_ocid: OCID) -> ScientificEvent | None:
        raise NotImplementedError

    @abstractmethod
    def list_for_subject(self, subject_ocid: OCID) -> Iterable[ScientificEvent]:
        raise NotImplementedError

    @abstractmethod
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        raise NotImplementedError

    @abstractmethod
    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        raise NotImplementedError


class ScientificRuntime(ABC):
    """Contract for transaction-scoped orchestration across Kernel services."""

    @abstractmethod
    def execute(self, request: RuntimeRequest) -> RuntimeResult:
        raise NotImplementedError

    @abstractmethod
    def get_result(self, correlation_id: str) -> RuntimeResult | None:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, correlation_id: str) -> RuntimeResult:
        raise NotImplementedError
