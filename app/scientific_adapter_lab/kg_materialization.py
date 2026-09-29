"""OC-KG-001 — Knowledge Graph materialization schema, governed pipeline, and read-through contract.

Governed, schema-versioned Knowledge Graph materialization pipeline that reads from
canonical scientific sources (taxonomy, literature, traits, interactions) and produces
KG-ready records — without autonomous publication.

Key invariants:
- automatic_publication=False and knowledge_graph_mutation=False are enforced at construction.
- UNKNOWN (not zero) is returned when the KG is unavailable; edges are never fabricated.
- Authoritative reviewed assessments outrank unreviewed imports.
- No graph database connectivity required in this slice; the read-through gateway uses
  an explicit unavailable stub.
- No production KG mutation, no taxonomy activation, no scientific publication.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

SCHEMA_VERSION = "oc-kg-materialization/v1"


class SourceDomain(str, Enum):
    TAXONOMY = "taxonomy"
    LITERATURE = "literature"
    TRAITS = "traits"
    INTERACTIONS = "interactions"
    UNKNOWN_DOMAIN = "UNKNOWN_DOMAIN"


class KGEvidenceState(str, Enum):
    CANONICAL_REVIEWED = "canonical_reviewed"
    CANONICAL_UNREVIEWED = "canonical_unreviewed"
    EXTERNAL_DISCOVERY = "external_discovery"
    UNAVAILABLE = "UNAVAILABLE"


_SOURCE_PRECEDENCE = {
    KGEvidenceState.CANONICAL_REVIEWED: 3,
    KGEvidenceState.CANONICAL_UNREVIEWED: 2,
    KGEvidenceState.EXTERNAL_DISCOVERY: 1,
    KGEvidenceState.UNAVAILABLE: 0,
}


class EdgePresence(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


@dataclass
class KnowledgeGraphPipeline:
    """Governed KG materialization pipeline configuration.

    Enforces at construction that automatic publication and KG mutation are
    both disabled. Neither flag may be set to True without explicit owner
    authorization and a separate governed publication step.
    """

    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False

    def __post_init__(self) -> None:
        if self.automatic_publication:
            raise ValueError(
                "KG_PIPELINE_GOVERNANCE_VIOLATION: automatic_publication must be False; "
                "no autonomous KG publication is permitted"
            )
        if self.knowledge_graph_mutation:
            raise ValueError(
                "KG_PIPELINE_GOVERNANCE_VIOLATION: knowledge_graph_mutation must be False; "
                "no autonomous KG mutation is permitted"
            )


@dataclass(frozen=True)
class KGMaterializationRecord:
    """Immutable KG-ready record capturing a single governed materialization result."""

    record_id: str
    source_domain: SourceDomain
    evidence_state: KGEvidenceState
    taxon_id: str
    taxon_name: str
    subject_entity: str
    predicate: str
    object_entity: str
    provenance_chain: tuple[str, ...]
    human_review_required: bool   # always True for governed records
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        if not self.record_id:
            raise ValueError("KG_RECORD_INVALID: record_id must not be empty")
        if not self.human_review_required:
            raise ValueError(
                "KG_RECORD_INVALID: human_review_required must be True; "
                "KG records are never auto-approved"
            )
        if not self.provenance_chain:
            raise ValueError("KG_RECORD_INVALID: provenance_chain must not be empty")

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "source_domain": self.source_domain.value,
            "evidence_state": self.evidence_state.value,
            "taxon_id": self.taxon_id,
            "taxon_name": self.taxon_name,
            "subject_entity": self.subject_entity,
            "predicate": self.predicate,
            "object_entity": self.object_entity,
            "provenance_chain": list(self.provenance_chain),
            "human_review_required": self.human_review_required,
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True)


class KGReadThroughGateway:
    """Read-through gateway that returns UNKNOWN when the KG is unavailable.

    Never fabricates the presence of edges. UNKNOWN is the correct sentinel
    for "not in the graph yet" vs. ABSENT which means "confirmed not present".
    """

    def __init__(self, *, available: bool = False) -> None:
        self._available = available

    def get_edge_presence(self, subject: str, predicate: str, obj: str) -> EdgePresence:
        """Return edge presence, defaulting to UNKNOWN when KG is unavailable.

        Args:
            subject: Subject entity identifier.
            predicate: Predicate / relationship type.
            obj: Object entity identifier.

        Returns:
            EdgePresence.UNKNOWN when the KG is unavailable (stub mode).
            Real implementations return PRESENT or ABSENT from the graph.
        """
        if not self._available:
            return EdgePresence.UNKNOWN
        raise NotImplementedError(
            "KG_READ_THROUGH_NOT_IMPLEMENTED: real graph connectivity is not available "
            "in this slice; use the stub (available=False) or connect a real KG adapter"
        )

    def is_available(self) -> bool:
        return self._available


class KGSourcePrecedence:
    """Arbitrates between competing KG materialization records.

    Rule: canonical_reviewed > canonical_unreviewed > external_discovery > unavailable.
    """

    def resolve(self, records: list[KGMaterializationRecord]) -> KGMaterializationRecord:
        if not records:
            raise ValueError("KG_PRECEDENCE_EMPTY: at least one record required")
        return max(records, key=lambda r: _SOURCE_PRECEDENCE.get(r.evidence_state, 0))

    def is_authoritative(self, record: KGMaterializationRecord) -> bool:
        return record.evidence_state == KGEvidenceState.CANONICAL_REVIEWED


def build_unavailable_kg_stubs(
    taxon_ids: list[str],
    *,
    predicate: str = "has_unknown_relation",
) -> list[KGMaterializationRecord]:
    """Return UNKNOWN/UNAVAILABLE stub records when the KG is absent.

    No edges are fabricated. Each returned record carries
    KGEvidenceState.UNAVAILABLE and EdgePresence.UNKNOWN.

    Args:
        taxon_ids: Taxon IDs to build unavailable stubs for.
        predicate: Predicate label to use in the stubs (default generic).

    Returns:
        A list of KGMaterializationRecord with evidence_state=UNAVAILABLE
        and human_review_required=True for every requested taxon_id.
    """
    return [
        KGMaterializationRecord(
            record_id=f"unavailable:{tid}",
            source_domain=SourceDomain.UNKNOWN_DOMAIN,
            evidence_state=KGEvidenceState.UNAVAILABLE,
            taxon_id=tid,
            taxon_name="",
            subject_entity=tid,
            predicate=predicate,
            object_entity=EdgePresence.UNKNOWN.value,
            provenance_chain=("NO_KG_CONNECTION",),
            human_review_required=True,
        )
        for tid in taxon_ids
    ]
