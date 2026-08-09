from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AggregateType(StrEnum):
    TAXON_IDENTITY_AGGREGATE = "TAXON_IDENTITY_AGGREGATE"
    TAXON_NAME_USAGE_AGGREGATE = "TAXON_NAME_USAGE_AGGREGATE"
    TRAIT_AGGREGATE = "TRAIT_AGGREGATE"
    MORPHOLOGICAL_CHARACTER_AGGREGATE = "MORPHOLOGICAL_CHARACTER_AGGREGATE"
    GLOSSARY_CONCEPT_AGGREGATE = "GLOSSARY_CONCEPT_AGGREGATE"
    POLLINATOR_ASSOCIATION_AGGREGATE = "POLLINATOR_ASSOCIATION_AGGREGATE"
    MYCORRHIZAL_ASSOCIATION_AGGREGATE = "MYCORRHIZAL_ASSOCIATION_AGGREGATE"
    HABITAT_AGGREGATE = "HABITAT_AGGREGATE"
    GEOGRAPHIC_DISTRIBUTION_AGGREGATE = "GEOGRAPHIC_DISTRIBUTION_AGGREGATE"
    PHENOLOGY_AGGREGATE = "PHENOLOGY_AGGREGATE"
    MEASUREMENT_AGGREGATE = "MEASUREMENT_AGGREGATE"
    ENVIRONMENTAL_TOLERANCE_AGGREGATE = "ENVIRONMENTAL_TOLERANCE_AGGREGATE"
    CONSERVATION_THREAT_AGGREGATE = "CONSERVATION_THREAT_AGGREGATE"
    CONSERVATION_ACTION_AGGREGATE = "CONSERVATION_ACTION_AGGREGATE"
    CULTIVATION_METHOD_AGGREGATE = "CULTIVATION_METHOD_AGGREGATE"
    DNA_MARKER_AGGREGATE = "DNA_MARKER_AGGREGATE"
    MOLECULAR_RESULT_AGGREGATE = "MOLECULAR_RESULT_AGGREGATE"
    ECOLOGICAL_INTERACTION_AGGREGATE = "ECOLOGICAL_INTERACTION_AGGREGATE"
    MECHANISTIC_RELATIONSHIP_AGGREGATE = "MECHANISTIC_RELATIONSHIP_AGGREGATE"
    SPECIMEN_REFERENCE_AGGREGATE = "SPECIMEN_REFERENCE_AGGREGATE"
    OCCURRENCE_ASSERTION_AGGREGATE = "OCCURRENCE_ASSERTION_AGGREGATE"


class EvidenceRelationship(StrEnum):
    SUPPORTS = "SUPPORTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DOES_NOT_SUPPORT = "DOES_NOT_SUPPORT"
    QUALIFIES = "QUALIFIES"
    REFINES = "REFINES"
    DUPLICATES = "DUPLICATES"
    SUPERSEDES = "SUPERSEDES"
    CORRECTS = "CORRECTS"
    DERIVES_FROM = "DERIVES_FROM"
    TEMPORALLY_REPLACES = "TEMPORALLY_REPLACES"
    GEOGRAPHICALLY_LIMITS = "GEOGRAPHICALLY_LIMITS"
    METHOD_DEPENDENT = "METHOD_DEPENDENT"
    TAXONOMICALLY_DEPENDENT = "TAXONOMICALLY_DEPENDENT"
    UNRESOLVED_RELATIONSHIP = "UNRESOLVED_RELATIONSHIP"


class ConsensusStatus(StrEnum):
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    SUPPORTED = "SUPPORTED"
    MIXED_EVIDENCE = "MIXED_EVIDENCE"
    CONFLICTING = "CONFLICTING"
    LIMITED_EVIDENCE = "LIMITED_EVIDENCE"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    METHOD_DEPENDENT = "METHOD_DEPENDENT"
    GEOGRAPHICALLY_LIMITED = "GEOGRAPHICALLY_LIMITED"
    TEMPORALLY_LIMITED = "TEMPORALLY_LIMITED"
    TAXONOMICALLY_AMBIGUOUS = "TAXONOMICALLY_AMBIGUOUS"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True)
class CandidateInput:
    candidate_id: int
    candidate_version: int
    candidate_type: str
    normalized_subject: str
    predicate: str
    object_value: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    source_revision_id: int = 0
    source_document_id: str = ""
    source_anchor_ids: tuple[int, ...] = ()
    evidence_type: str = "UNKNOWN"
    source_class: str = "UNKNOWN"
    directness: str = "INDIRECT"
    source_lineage: str | None = None
    citation_lineage: tuple[str, ...] = ()
    document_hash: str | None = None
    taxon_links: tuple[dict[str, Any], ...] = ()
    temporal_context: dict[str, Any] = field(default_factory=dict)
    geographic_context: dict[str, Any] = field(default_factory=dict)
    method_context: dict[str, Any] = field(default_factory=dict)
    population_context: dict[str, Any] = field(default_factory=dict)
    measurement_context: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    review_state: str = "REQUIRED"
    verification_state: str = "UNVERIFIED"
    status: str = "ACTIVE"
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.candidate_id <= 0 or self.candidate_version <= 0 or self.source_revision_id <= 0:
            raise ValueError("INVALID_CANDIDATE_IDENTITY")
        if not self.normalized_subject.strip() or not self.predicate.strip():
            raise ValueError("INVALID_ASSERTION_IDENTITY")
        if not self.source_anchor_ids:
            raise ValueError("EXACT_SOURCE_ANCHORS_REQUIRED")
        if self.object_value is None and self.numeric_value is None:
            raise ValueError("CANDIDATE_VALUE_REQUIRED")
        if not 0 <= self.confidence <= 1:
            raise ValueError("INVALID_CONFIDENCE")


CANDIDATE_TYPE_MAP = {
    "TAXON": AggregateType.TAXON_IDENTITY_AGGREGATE,
    "TAXON_NAME_USAGE": AggregateType.TAXON_NAME_USAGE_AGGREGATE,
    "TRAIT": AggregateType.TRAIT_AGGREGATE,
    "MORPHOLOGY_TERM": AggregateType.MORPHOLOGICAL_CHARACTER_AGGREGATE,
    "GLOSSARY": AggregateType.GLOSSARY_CONCEPT_AGGREGATE,
    "POLLINATOR_ASSOCIATION": AggregateType.POLLINATOR_ASSOCIATION_AGGREGATE,
    "MYCORRHIZAL_ASSOCIATION": AggregateType.MYCORRHIZAL_ASSOCIATION_AGGREGATE,
    "HABITAT": AggregateType.HABITAT_AGGREGATE,
    "GEOGRAPHIC_OCCURRENCE": AggregateType.GEOGRAPHIC_DISTRIBUTION_AGGREGATE,
    "PHENOLOGY_EVENT": AggregateType.PHENOLOGY_AGGREGATE,
    "MEASUREMENT": AggregateType.MEASUREMENT_AGGREGATE,
    "ENVIRONMENTAL_TOLERANCE": AggregateType.ENVIRONMENTAL_TOLERANCE_AGGREGATE,
    "CONSERVATION_ASSERTION": AggregateType.CONSERVATION_THREAT_AGGREGATE,
    "CONSERVATION_ACTION": AggregateType.CONSERVATION_ACTION_AGGREGATE,
    "CULTIVATION_OBSERVATION": AggregateType.CULTIVATION_METHOD_AGGREGATE,
    "MOLECULAR_MARKER": AggregateType.DNA_MARKER_AGGREGATE,
    "MOLECULAR_RESULT": AggregateType.MOLECULAR_RESULT_AGGREGATE,
    "ECOLOGICAL_RELATIONSHIP": AggregateType.ECOLOGICAL_INTERACTION_AGGREGATE,
    "MECHANISTIC_RELATIONSHIP": AggregateType.MECHANISTIC_RELATIONSHIP_AGGREGATE,
    "SPECIMEN_REFERENCE": AggregateType.SPECIMEN_REFERENCE_AGGREGATE,
    "OCCURRENCE": AggregateType.OCCURRENCE_ASSERTION_AGGREGATE,
}
