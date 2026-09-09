"""OC-COMPLETE-009 — Scientific Adapter Laboratory: GloBI interaction adapter
and open-source capability candidate matrix (issue #1089).

Governed interaction schema and normalization pipeline binding Global Biotic
Interactions (GloBI) dataset records to canonical orchid taxonomy and evidence
contracts.

Key invariants:
- Raw interaction records are PROVISIONAL until canonical taxon reconciliation.
- UNKNOWN is the correct sentinel when interaction data is absent.
- review_required=True and auto_promotion_blocked=True on all KG candidates.
- No live GloBI API required; gateway uses an explicit unavailable stub.
- No production DB mutation, no taxonomy activation, no automated publication.
- Candidate tool matrix records KEEP/ADAPT/FEDERATE/REJECT decisions — no
  auto-import of upstream code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = "oc-interaction-lab/v1"


class InteractionType(str, Enum):
    POLLINATES = "pollinates"
    POLLINATED_BY = "pollinated_by"
    VISITS_FLOWERS_OF = "visits_flowers_of"
    SYMBIONT_OF = "symbiont_of"
    PARASITE_OF = "parasite_of"
    HERBIVORE_OF = "herbivore_of"
    UNKNOWN_INTERACTION = "UNKNOWN_INTERACTION"


class InteractionSource(str, Enum):
    GLOBI = "GloBI"
    INAT = "iNaturalist"
    MANUAL_REVIEW = "manual_review"
    UNAVAILABLE = "unavailable"


class InteractionEvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNKNOWN = "UNKNOWN"


class ToolEvaluation(str, Enum):
    KEEP = "KEEP"
    ADAPT = "ADAPT"
    FEDERATE = "FEDERATE"
    PORT_CONCEPT = "PORT_CONCEPT"
    REJECT = "REJECT"


_EVIDENCE_PRECEDENCE: dict[InteractionEvidenceState, int] = {
    InteractionEvidenceState.VERIFIED: 3,
    InteractionEvidenceState.PROVISIONAL: 2,
    InteractionEvidenceState.UNKNOWN: 0,
}

_INTERACTION_TYPE_MAP: dict[str, InteractionType] = {
    "pollinates": InteractionType.POLLINATES,
    "pollinated by": InteractionType.POLLINATED_BY,
    "is pollinated by": InteractionType.POLLINATED_BY,
    "RO:0002455": InteractionType.POLLINATES,
    "RO:0002456": InteractionType.POLLINATED_BY,
    "visits flowers of": InteractionType.VISITS_FLOWERS_OF,
    "RO:0002472": InteractionType.VISITS_FLOWERS_OF,
    "symbiont of": InteractionType.SYMBIONT_OF,
    "is symbiont of": InteractionType.SYMBIONT_OF,
    "RO:0002622": InteractionType.SYMBIONT_OF,
    "parasite of": InteractionType.PARASITE_OF,
    "parasiteOf": InteractionType.PARASITE_OF,
    "RO:0002453": InteractionType.PARASITE_OF,
    "herbivore of": InteractionType.HERBIVORE_OF,
    "eats": InteractionType.HERBIVORE_OF,
}


@dataclass(frozen=True)
class RawInteractionRecord:
    """Unvalidated interaction record as received from a provider (e.g. GloBI)."""

    record_id: str
    source_taxon_name: str
    target_taxon_name: str
    interaction_type_name: str
    interaction_type_id: str        # RO term URI or "" when absent
    citation: str
    dataset_name: str
    dataset_doi: str
    provider: InteractionSource

    def validate(self) -> None:
        if not self.record_id:
            raise ValueError("RAW_INTERACTION_INVALID: record_id must not be empty")
        if not self.source_taxon_name:
            raise ValueError("RAW_INTERACTION_INVALID: source_taxon_name required")
        if not self.target_taxon_name:
            raise ValueError("RAW_INTERACTION_INVALID: target_taxon_name required")
        if not self.interaction_type_name and not self.interaction_type_id:
            raise ValueError("RAW_INTERACTION_INVALID: interaction type name or id required")


@dataclass(frozen=True)
class NormalizedInteraction:
    """Interaction record after normalization and canonical taxon reconciliation."""

    record_id: str
    source_taxon_name: str
    source_taxon_id: str            # canonical OC taxon ID or "" when unresolved
    target_taxon_name: str
    target_taxon_id: str            # canonical OC taxon ID or "" when unresolved
    interaction_type: InteractionType
    evidence_state: InteractionEvidenceState
    citation: str
    dataset_source: InteractionSource
    provenance_chain: tuple[str, ...]
    taxon_resolved: bool

    def validate(self) -> None:
        if not self.record_id:
            raise ValueError("NORMALIZED_INTERACTION_INVALID: record_id required")
        if self.evidence_state is InteractionEvidenceState.VERIFIED and not self.taxon_resolved:
            raise ValueError("VERIFIED_STATE_REQUIRES_RESOLVED_TAXON")

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_taxon_name": self.source_taxon_name,
            "source_taxon_id": self.source_taxon_id or None,
            "target_taxon_name": self.target_taxon_name,
            "target_taxon_id": self.target_taxon_id or None,
            "interaction_type": self.interaction_type.value,
            "evidence_state": self.evidence_state.value,
            "citation": self.citation,
            "dataset_source": self.dataset_source.value,
            "provenance_chain": list(self.provenance_chain),
            "taxon_resolved": self.taxon_resolved,
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True)


@dataclass(frozen=True)
class KGCandidateInteraction:
    """Review-bound KG candidate — requires human approval before graph mutation."""

    normalized: NormalizedInteraction
    review_required: bool = True
    auto_promotion_blocked: bool = True
    graph_mutation: bool = False
    candidate_state: str = "PENDING_REVIEW"

    def __post_init__(self) -> None:
        if self.review_required is False:
            raise PermissionError("KG_CANDIDATE_REVIEW_REQUIRED_INVARIANT: review_required must be True")
        if self.auto_promotion_blocked is False:
            raise PermissionError("KG_CANDIDATE_AUTO_PROMOTION_BLOCKED_INVARIANT: auto_promotion_blocked must be True")
        if self.graph_mutation is True:
            raise PermissionError("KG_CANDIDATE_GRAPH_MUTATION_INVARIANT: graph_mutation must be False")


@dataclass(frozen=True)
class CandidateTool:
    """Scientific tool candidate evaluated for reuse in OC architecture."""

    repo: str
    tool_name: str
    license: str
    evaluation: ToolEvaluation
    capability_summary: str
    reuse_pattern: str
    orchid_relevance: str
    rejection_reason: str = ""

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "tool_name": self.tool_name,
            "license": self.license,
            "evaluation": self.evaluation.value,
            "capability_summary": self.capability_summary,
            "reuse_pattern": self.reuse_pattern,
            "orchid_relevance": self.orchid_relevance,
            "rejection_reason": self.rejection_reason or None,
        }


@dataclass
class CapabilityCandidateMatrix:
    """Machine-readable matrix of open-source scientific capability candidates."""

    schema_version: str = SCHEMA_VERSION
    candidates: list[CandidateTool] = field(default_factory=list)

    def add(self, candidate: CandidateTool) -> None:
        self.candidates.append(candidate)

    def by_evaluation(self, evaluation: ToolEvaluation) -> list[CandidateTool]:
        return [c for c in self.candidates if c.evaluation is evaluation]

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "total": len(self.candidates),
            "candidates": [c.to_safe_dict() for c in self.candidates],
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True, indent=2)


def map_interaction_type(raw_type: str) -> InteractionType:
    """Map a raw interaction term (name or RO ID) to the canonical enum."""
    return _INTERACTION_TYPE_MAP.get(raw_type.strip(), InteractionType.UNKNOWN_INTERACTION)


def normalize_interaction(
    raw: RawInteractionRecord,
    *,
    source_taxon_id: str = "",
    target_taxon_id: str = "",
) -> NormalizedInteraction:
    """Normalize a raw interaction record to canonical evidence state.

    Pure function — no external calls. Caller provides pre-resolved taxon IDs
    (empty string when unresolvable). Evidence is PROVISIONAL when taxon IDs
    are absent; VERIFIED when both are present and provider is not UNAVAILABLE.
    """
    raw.validate()

    interaction_type = map_interaction_type(
        raw.interaction_type_id or raw.interaction_type_name
    )

    taxon_resolved = bool(source_taxon_id and target_taxon_id)
    if raw.provider is InteractionSource.UNAVAILABLE:
        evidence_state = InteractionEvidenceState.UNKNOWN
    elif taxon_resolved:
        evidence_state = InteractionEvidenceState.VERIFIED
    else:
        evidence_state = InteractionEvidenceState.PROVISIONAL

    return NormalizedInteraction(
        record_id=raw.record_id,
        source_taxon_name=raw.source_taxon_name,
        source_taxon_id=source_taxon_id,
        target_taxon_name=raw.target_taxon_name,
        target_taxon_id=target_taxon_id,
        interaction_type=interaction_type,
        evidence_state=evidence_state,
        citation=raw.citation,
        dataset_source=raw.provider,
        provenance_chain=(raw.dataset_name, raw.dataset_doi, raw.provider.value),
        taxon_resolved=taxon_resolved,
    )


def build_unavailable_interaction(taxon_name: str) -> NormalizedInteraction:
    """Return UNKNOWN sentinel when interaction data is absent. Never fabricate."""
    return NormalizedInteraction(
        record_id="unavailable",
        source_taxon_name=taxon_name,
        source_taxon_id="",
        target_taxon_name="",
        target_taxon_id="",
        interaction_type=InteractionType.UNKNOWN_INTERACTION,
        evidence_state=InteractionEvidenceState.UNKNOWN,
        citation="",
        dataset_source=InteractionSource.UNAVAILABLE,
        provenance_chain=("unavailable",),
        taxon_resolved=False,
    )


def stage_interaction_for_review(
    normalized: NormalizedInteraction,
) -> KGCandidateInteraction:
    """Stage a normalized interaction for human KG review. No graph writes."""
    normalized.validate()
    return KGCandidateInteraction(
        normalized=normalized,
        review_required=True,
        auto_promotion_blocked=True,
        graph_mutation=False,
        candidate_state="PENDING_REVIEW",
    )


def resolve_interaction_precedence(
    interactions: list[NormalizedInteraction],
) -> NormalizedInteraction | None:
    """Return the highest-precedence interaction (VERIFIED > PROVISIONAL > UNKNOWN)."""
    if not interactions:
        return None
    return max(
        interactions,
        key=lambda r: _EVIDENCE_PRECEDENCE.get(r.evidence_state, 0),
    )


class InteractionGateway:
    """Read-through gateway stub — raises when live, returns UNKNOWN when unavailable."""

    def __init__(self, *, available: bool = False) -> None:
        self._available = available

    def fetch_orchid_interactions(
        self,
        taxon_name: str,
        *,
        interaction_type: InteractionType | None = None,
    ) -> list[NormalizedInteraction]:
        if self._available:
            raise NotImplementedError(
                "Live GloBI API not wired; implement provider connector"
            )
        return [build_unavailable_interaction(taxon_name)]


def build_gloBi_candidate_matrix() -> CapabilityCandidateMatrix:
    """Build the machine-readable candidate matrix for GloBI and related tools.

    Evaluations are static and require no live repo inspection. Based on
    published licenses and documented API capabilities.
    """
    matrix = CapabilityCandidateMatrix()

    matrix.add(CandidateTool(
        repo="globalbioticinteractions/globalbioticinteractions",
        tool_name="GloBI interaction data",
        license="CC0 / CC BY (per dataset)",
        evaluation=ToolEvaluation.FEDERATE,
        capability_summary=(
            "Provider-specific interaction datasets with taxon alignment, "
            "citation provenance, and Darwin Core format"
        ),
        reuse_pattern="Read-only API/data federation; do not copy dataset configs",
        orchid_relevance=(
            "Orchid-pollinator and orchid-mycorrhizal interaction records available"
        ),
    ))
    matrix.add(CandidateTool(
        repo="globalbioticinteractions/nomer",
        tool_name="nomer",
        license="Apache 2.0",
        evaluation=ToolEvaluation.ADAPT,
        capability_summary=(
            "Taxon name alignment across GBIF, NCBI, ITIS, WFO, iNaturalist"
        ),
        reuse_pattern=(
            "Port name-alignment concept into OC canonical taxon resolver; "
            "do not import JAR binary"
        ),
        orchid_relevance=(
            "Essential for resolving raw taxon names from interaction records "
            "to canonical OC taxa"
        ),
    ))
    matrix.add(CandidateTool(
        repo="globalbioticinteractions/elton",
        tool_name="elton",
        license="Apache 2.0",
        evaluation=ToolEvaluation.PORT_CONCEPT,
        capability_summary=(
            "Dataset harvester CLI: provider-specific config to normalized "
            "interaction stream"
        ),
        reuse_pattern=(
            "Port provider-adapter isolation pattern to OC; "
            "do not import CLI binary"
        ),
        orchid_relevance=(
            "Provider-adapter pattern matches OC scientific_adapter_lab architecture"
        ),
    ))
    matrix.add(CandidateTool(
        repo="oborel/obo-relations",
        tool_name="Relation Ontology (RO)",
        license="CC BY 4.0",
        evaluation=ToolEvaluation.ADAPT,
        capability_summary=(
            "Formal interaction term definitions: pollinates, symbiont_of, parasite_of"
        ),
        reuse_pattern=(
            "Map RO term IDs to OC InteractionType enum; "
            "do not import full OWL ontology"
        ),
        orchid_relevance=(
            "Canonical vocabulary for ecological interaction types used by GloBI"
        ),
    ))
    matrix.add(CandidateTool(
        repo="globalbioticinteractions/template-dataset",
        tool_name="GloBI dataset template",
        license="CC0",
        evaluation=ToolEvaluation.PORT_CONCEPT,
        capability_summary=(
            "Standardized provider dataset format: species_list, interactions, sources"
        ),
        reuse_pattern="Reference format for structuring raw interaction data before normalization",
        orchid_relevance="Reference for provider dataset ingestion structure",
    ))

    return matrix
