from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    source_id: str
    title: str
    content_hash: str
    canonical_uri: str | None = None

    def validate(self) -> None:
        if not self.source_id.strip() or not self.title.strip():
            raise ValueError("SOURCE_IDENTITY_REQUIRED")
        if len(self.content_hash) < 32:
            raise ValueError("SOURCE_CONTENT_HASH_INVALID")


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    start: int
    end: int
    text: str

    def validate(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("EVIDENCE_SPAN_INVALID")
        if not self.text.strip():
            raise ValueError("EVIDENCE_TEXT_REQUIRED")


@dataclass(frozen=True, slots=True)
class LiteratureClaim:
    claim_id: str
    source: SourceIdentity
    evidence_spans: tuple[EvidenceSpan, ...]
    predicate: str
    object_value: str
    canonical_taxon_id: str | None = None
    confidence: float | None = None
    contradictions: tuple[str, ...] = ()

    def validate(self) -> None:
        self.source.validate()
        if not self.claim_id.strip() or not self.predicate.strip() or not self.object_value.strip():
            raise ValueError("LITERATURE_CLAIM_REQUIRED")
        if not self.evidence_spans:
            raise ValueError("EVIDENCE_SPAN_REQUIRED")
        for span in self.evidence_spans:
            span.validate()
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CONFIDENCE_OUT_OF_RANGE")


@dataclass(frozen=True, slots=True)
class CharacterDefinition:
    character_id: str
    label: str
    allowed_states: tuple[str, ...]
    weight: float = 1.0

    def validate(self) -> None:
        if not self.character_id.strip() or not self.label.strip() or not self.allowed_states:
            raise ValueError("CHARACTER_DEFINITION_INVALID")
        if self.weight <= 0:
            raise ValueError("CHARACTER_WEIGHT_INVALID")


@dataclass(frozen=True, slots=True)
class CharacterObservation:
    character_id: str
    state: str | None
    confidence: float
    provenance: tuple[str, ...]

    def validate(self) -> None:
        if not self.character_id.strip():
            raise ValueError("CHARACTER_ID_REQUIRED")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CONFIDENCE_OUT_OF_RANGE")
        if not self.provenance:
            raise ValueError("OBSERVATION_PROVENANCE_REQUIRED")


@dataclass(frozen=True, slots=True)
class MatrixProfile:
    taxon_id: str
    accepted_name: str
    states: Mapping[str, frozenset[str]]
    provenance: tuple[str, ...]

    def validate(self) -> None:
        if not self.taxon_id.strip() or not self.accepted_name.strip() or not self.provenance:
            raise ValueError("MATRIX_PROFILE_INVALID")


@dataclass(frozen=True, slots=True)
class CharacterContribution:
    character_id: str
    observed_state: str | None
    expected_states: tuple[str, ...]
    outcome: str
    weighted_score: float


@dataclass(frozen=True, slots=True)
class MatrixCandidate:
    taxon_id: str
    accepted_name: str
    score: float
    support_count: int
    contradiction_count: int
    unknown_count: int
    contributions: tuple[CharacterContribution, ...]


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    provider: str
    model_name: str
    model_version: str
    inference_id: str

    def validate(self) -> None:
        if not all(value.strip() for value in (self.provider, self.model_name, self.model_version, self.inference_id)):
            raise ValueError("MODEL_PROVENANCE_REQUIRED")


@dataclass(frozen=True, slots=True)
class PlantPartDetection:
    part: str
    confidence: float

    def validate(self) -> None:
        if not self.part.strip() or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("PLANT_PART_DETECTION_INVALID")


@dataclass(frozen=True, slots=True)
class ImageAnalysisResult:
    image_id: str
    content_hash: str
    license_code: str
    attribution: str
    model: ModelProvenance
    detected_parts: tuple[PlantPartDetection, ...]
    character_observations: tuple[CharacterObservation, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.image_id.strip() or len(self.content_hash) < 32:
            raise ValueError("IMAGE_IDENTITY_INVALID")
        if not self.license_code.strip() or not self.attribution.strip():
            raise PermissionError("LICENSE_AND_ATTRIBUTION_REQUIRED")
        self.model.validate()
        if not self.detected_parts:
            raise ValueError("PLANT_PART_DETECTION_REQUIRED")
        for part in self.detected_parts:
            part.validate()
        for observation in self.character_observations:
            observation.validate()
        if any(observation.confidence > 0.98 for observation in self.character_observations):
            raise ValueError("UNSUPPORTED_VISION_CONFIDENCE")
