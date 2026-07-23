"""Abstract service contracts for future Scientific Kernel engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .identity import OCID
from .models import ScientificObject


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
