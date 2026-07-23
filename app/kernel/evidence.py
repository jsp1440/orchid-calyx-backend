"""Immutable scientific evidence and provenance models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class EvidenceType(str, Enum):
    """Canonical evidence categories accepted by the Scientific Kernel."""

    PUBLICATION = "publication"
    SPECIMEN = "specimen"
    IMAGE = "image"
    OBSERVATION = "observation"
    DNA_SEQUENCE = "dna_sequence"
    DATASET = "dataset"
    EXPERIMENT = "experiment"
    EXPERT_REVIEW = "expert_review"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Immutable record describing where evidence came from and how it was acquired."""

    source_name: str
    source_record_id: str
    source_url: str | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    collector: str | None = None
    method: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source_name = self.source_name.strip()
        source_record_id = self.source_record_id.strip()
        if not source_name:
            raise ScientificObjectValidationError("provenance source_name must not be empty")
        if not source_record_id:
            raise ScientificObjectValidationError("provenance source_record_id must not be empty")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ScientificObjectValidationError("provenance retrieved_at must be timezone-aware")
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "source_record_id", source_record_id)
        object.__setattr__(self, "retrieved_at", self.retrieved_at.astimezone(timezone.utc))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class Evidence(ScientificObject):
    """Immutable evidence object used to support scientific assertions."""

    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.EVIDENCE))
    object_type: str = "evidence"
    evidence_type: EvidenceType = EvidenceType.OTHER
    title: str = ""
    provenance: Provenance = field(default_factory=lambda: Provenance("unknown", "unknown"))
    citation: str | None = None
    content: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        ScientificObject.__post_init__(self)
        if self.ocid.kind is not OCIDKind.EVIDENCE:
            raise ScientificObjectValidationError("evidence requires an EVIDENCE OCID")
        title = self.title.strip()
        if not title:
            raise ScientificObjectValidationError("evidence title must not be empty")
        content = MappingProxyType(dict(self.content))
        payload = {
            "evidence_type": self.evidence_type.value,
            "title": title,
            "citation": self.citation,
            "provenance": {
                "source_name": self.provenance.source_name,
                "source_record_id": self.provenance.source_record_id,
                "source_url": self.provenance.source_url,
            },
            "content": dict(content),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "fingerprint", fingerprint)
