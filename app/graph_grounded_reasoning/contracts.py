"""Versioned contract for the graph-grounded scientific reasoning pilot.

Pilot scope (see ``docs/architecture/GRAPH-GROUNDED-REASONING-PILOT.md``):

``question -> canonical taxon resolution -> bounded one-hop graph retrieval ->
exact-document literature anchoring -> evidence packet -> deterministic
composition -> fail-closed validation -> cited result``

Every limit below is part of the contract.  Nothing in this package writes to
the Knowledge Graph, the semantic index or any database, calls a model
provider, or publishes scientific knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.scientific_inference.models import InferenceState

CONTRACT_VERSION = "oc-graph-grounded-reasoning-v1"
COMPOSER_VERSION = "ggr-deterministic-composer-1"
VALIDATOR_VERSION = "ggr-validator-1"

GRAPH_DEPTH = 1
MAX_TAXA_PER_QUESTION = 3
MAX_GRAPH_RECORDS = 25
MAX_EVIDENCE_RECORDS = 10
MAX_QUESTION_LENGTH = 500

#: The only graph-edge payload key the pilot reads as evidence: the
#: claim-level provenance contract (``runtime.knowledge_graph.claim_provenance``).
#: Everything else on an edge is ignored, so coordinates, locality strings and
#: private fields never travel into a packet.
PAYLOAD_ALLOWLIST: frozenset[str] = frozenset({"claim_provenance"})

#: Keys that must never appear anywhere in a returned result.
FORBIDDEN_RESULT_KEYS: frozenset[str] = frozenset(
    {
        "latitude",
        "longitude",
        "decimal_latitude",
        "decimal_longitude",
        "coordinates",
        "locality",
        "verbatim_locality",
    }
)


class Facet(StrEnum):
    """The typed question intent.  No free-text intent parsing in the pilot."""

    TAXONOMY = "TAXONOMY"
    MORPHOLOGY = "MORPHOLOGY"
    DESCRIPTION = "DESCRIPTION"
    POLLINATION = "POLLINATION"
    MYCORRHIZA = "MYCORRHIZA"
    DISTRIBUTION = "DISTRIBUTION"


#: Facet -> Knowledge Graph vocabulary domains (``runtime.knowledge_graph.vocabulary``).
FACET_DOMAINS: dict[Facet, frozenset[str]] = {
    Facet.TAXONOMY: frozenset({"taxonomy"}),
    Facet.MORPHOLOGY: frozenset({"traits"}),
    Facet.DESCRIPTION: frozenset({"literature", "traits", "habitat"}),
    Facet.POLLINATION: frozenset({"pollinators"}),
    Facet.MYCORRHIZA: frozenset({"mycorrhiza"}),
    Facet.DISTRIBUTION: frozenset({"geography", "occurrences"}),
}


class ResolutionState(StrEnum):
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_VIA_SYNONYM = "RESOLVED_VIA_SYNONYM"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class AnchorState(StrEnum):
    ANCHORED = "ANCHORED"
    ANCHOR_UNAVAILABLE = "ANCHOR_UNAVAILABLE"
    SOURCE_UNDECLARED = "SOURCE_UNDECLARED"
    PROVENANCE_INVALID = "PROVENANCE_INVALID"
    SOURCE_REVISION_MISMATCH = "SOURCE_REVISION_MISMATCH"
    TAXON_BINDING_MISMATCH = "TAXON_BINDING_MISMATCH"


class ResultState(StrEnum):
    """Answer-level state.  The first four are SCIAN-002 ``InferenceState``s."""

    CANDIDATE = InferenceState.CANDIDATE.value
    REVIEW_REQUIRED = InferenceState.REVIEW_REQUIRED.value
    CONFLICT_REVIEW_REQUIRED = InferenceState.CONFLICT_REVIEW_REQUIRED.value
    INSUFFICIENT_EVIDENCE = InferenceState.INSUFFICIENT_EVIDENCE.value
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(frozen=True)
class ScientificQuestion:
    text: str
    facet: Facet

    def __post_init__(self) -> None:
        normalized = " ".join(str(self.text or "").split())
        if not normalized or len(normalized) > MAX_QUESTION_LENGTH:
            raise ValueError("INVALID_QUESTION_LENGTH")
        object.__setattr__(self, "text", normalized)
        object.__setattr__(self, "facet", Facet(self.facet))


@dataclass(frozen=True)
class TaxonResolution:
    state: ResolutionState
    mentioned_names: tuple[str, ...]
    accepted_canonical_id: int | None = None
    accepted_name: str | None = None
    via_synonym: str | None = None
    candidates: tuple[dict[str, Any], ...] = ()
    authority: str | None = None
    release: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "mentioned_names": list(self.mentioned_names),
            "accepted_canonical_id": self.accepted_canonical_id,
            "accepted_name": self.accepted_name,
            "via_synonym": self.via_synonym,
            "candidates": [dict(c) for c in self.candidates],
            "authority": self.authority,
            "release": self.release,
        }


@dataclass(frozen=True)
class EvidenceItem:
    """One graph assertion, kept separate from every other assertion."""

    ref: str
    domain: str
    edge_type: str
    subject: str
    object_label: str
    polarity: int
    evidence_class: str | None
    review_state: str | None
    verification_state: str | None
    source_table: str | None
    source_pk: str | None
    source_document_id: str | None
    assertion_id: str | None
    conflicting_assertion_ids: tuple[str, ...]
    qualifier: str | None
    anchor_state: AnchorState
    citation: dict[str, Any] | None = None
    extraction_method: str | None = None
    confidence: float | None = None
    uncertainty: tuple[str, ...] = ()
    declared_anchors: tuple[dict[str, Any], ...] = ()
    taxon_binding: dict[str, Any] | None = None
    provenance_violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "domain": self.domain,
            "edge_type": self.edge_type,
            "subject": self.subject,
            "object_label": self.object_label,
            "polarity": self.polarity,
            "evidence_class": self.evidence_class,
            "review_state": self.review_state,
            "verification_state": self.verification_state,
            "provenance": {
                "source_table": self.source_table,
                "source_pk": self.source_pk,
                "source_document_id": self.source_document_id,
                "assertion_id": self.assertion_id,
            },
            "conflicting_assertion_ids": list(self.conflicting_assertion_ids),
            "qualifier": self.qualifier,
            "anchor_state": self.anchor_state.value,
            "citation": self.citation,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "confidence_is_probability": False,
            "uncertainty": list(self.uncertainty),
            "declared_anchors": [dict(a) for a in self.declared_anchors],
            "taxon_binding": self.taxon_binding,
            "provenance_violations": list(self.provenance_violations),
        }


@dataclass(frozen=True)
class EvidencePacket:
    contract_version: str
    question: ScientificQuestion
    resolution: TaxonResolution
    focal_node_key: str | None
    items: tuple[EvidenceItem, ...]
    conflicts: tuple[tuple[str, str], ...]
    gaps: tuple[str, ...]
    withheld_count: int
    truncated: bool
    limits: dict[str, int] = field(
        default_factory=lambda: {
            "graph_depth": GRAPH_DEPTH,
            "max_graph_records": MAX_GRAPH_RECORDS,
            "max_evidence_records": MAX_EVIDENCE_RECORDS,
            "max_taxa_per_question": MAX_TAXA_PER_QUESTION,
        }
    )

    def item(self, ref: str) -> EvidenceItem | None:
        return next((i for i in self.items if i.ref == ref), None)

    def facet_items(self) -> tuple[EvidenceItem, ...]:
        domains = FACET_DOMAINS[self.question.facet]
        return tuple(i for i in self.items if i.domain in domains)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "question": {"text": self.question.text, "facet": self.question.facet.value},
            "resolution": self.resolution.to_dict(),
            "focal_node_key": self.focal_node_key,
            "items": [i.to_dict() for i in self.items],
            "conflicts": [list(pair) for pair in self.conflicts],
            "gaps": list(self.gaps),
            "withheld_count": self.withheld_count,
            "truncated": self.truncated,
            "limits": dict(self.limits),
        }


@dataclass(frozen=True)
class Claim:
    statement: str
    subject_canonical_id: int | None
    refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "subject_canonical_id": self.subject_canonical_id,
            "refs": list(self.refs),
        }


@dataclass(frozen=True)
class Composition:
    state: ResultState
    claims: tuple[Claim, ...]
    conflicts: tuple[tuple[str, str], ...]
    uncertainty: tuple[str, ...]
    gaps: tuple[str, ...]
    composer_version: str = COMPOSER_VERSION
