"""Shared dataclasses for the offline scientific workflow.

These records are deliberately plain Python so they can be produced by the
rule-based extractor, consumed by the Matrix / dossier / Knowledge Graph
bridges, and serialised without a database.  Nothing in this module talks to
PostgreSQL, calls a paid provider, or mutates canonical stores.

Scientific safeguards implemented here:

* ``StateKind`` keeps ABSENT (a source explicitly states absence) distinct
  from UNKNOWN (not reported), INAPPLICABLE (the character cannot apply, e.g.
  spur length on a spurless flower) and CONTRADICTORY (sources disagree and
  the disagreement is preserved, not averaged away).
* Every observation carries a :class:`SourceCitation` and a provenance method,
  so literature-derived evidence and image-based (Vision) inference can never
  be silently merged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class StateKind(StrEnum):
    """Lifecycle of a character state for one taxon in one evidence context."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    INAPPLICABLE = "inapplicable"
    CONTRADICTORY = "contradictory"


class EvidenceKind(StrEnum):
    """Where an observation came from.  Never merge across kinds silently."""

    LITERATURE = "literature"
    VISION_INFERENCE = "vision_inference"
    HUMAN_ANNOTATION = "human_annotation"


class ProvenanceMethod(StrEnum):
    RULE_EXTRACTED = "rule_extracted"
    MODEL_EXTRACTED = "model_extracted"
    VISION_PROPOSED = "vision_proposed"
    HUMAN_ANNOTATED = "human_annotated"
    IMPORTED = "imported"


@dataclass(frozen=True)
class SourceCitation:
    """Bibliographic / fixture provenance for one evidence source."""

    source_id: str
    source_name: str
    source_type: str
    rights_status: str
    attribution: str
    license: str | None = None
    notes: str | None = None
    author: str | None = None
    year: int | None = None
    title: str | None = None
    doi: str | None = None
    url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class TextSpan:
    """Character offsets into the decoded source body plus the exact excerpt."""

    start: int
    end: int
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CharacterObservationRecord:
    """One extracted character state for one taxon from one source.

    ``value`` may be a string (categorical), a number (numeric), a
    ``{"min": …, "max": …}`` range, or ``None`` for ABSENT / UNKNOWN /
    INAPPLICABLE states.  Numeric measurements keep both the original unit
    and the millimetre-normalised value.
    """

    record_id: str
    taxon_id: str
    character_id: str
    state_kind: StateKind
    value: Any
    span: TextSpan | None
    source: SourceCitation
    provenance_method: ProvenanceMethod
    evidence_kind: EvidenceKind
    confidence: float
    extractor: str
    extractor_version: str
    unit_original: str | None = None
    unit_normalized: str | None = None
    value_normalized: Any = None
    review_status: str = "unreviewed"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state_kind"] = str(self.state_kind)
        payload["provenance_method"] = str(self.provenance_method)
        payload["evidence_kind"] = str(self.evidence_kind)
        return payload


@dataclass(frozen=True)
class CharacterStateView:
    """Aggregated view of all observations for one (taxon, character) pair.

    CONTRADICTORY views keep every contributing record visible; nothing is
    resolved by majority vote.
    """

    taxon_id: str
    character_id: str
    state_kind: StateKind
    value: Any
    unit_normalized: str | None
    value_normalized: Any
    records: tuple[CharacterObservationRecord, ...] = field(default_factory=tuple)
    disagreement: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def is_reported(self) -> bool:
        return self.state_kind in {StateKind.PRESENT, StateKind.ABSENT, StateKind.CONTRADICTORY}

    def as_dict(self) -> dict[str, Any]:
        return {
            "taxon_id": self.taxon_id,
            "character_id": self.character_id,
            "state_kind": str(self.state_kind),
            "value": self.value,
            "unit_normalized": self.unit_normalized,
            "value_normalized": self.value_normalized,
            "records": [record.as_dict() for record in self.records],
            "disagreement": list(self.disagreement),
        }


def stable_id(*parts: str, prefix: str) -> str:
    """Deterministic record id; identical inputs always produce the same id."""

    payload = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def json_dumps_stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str)
