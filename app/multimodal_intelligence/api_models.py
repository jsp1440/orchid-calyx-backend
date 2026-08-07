from __future__ import annotations

from pydantic import BaseModel, Field

from .contracts import (
    CharacterDefinition,
    CharacterObservation,
    EvidenceSpan,
    ImageAnalysisResult,
    LiteratureClaim,
    MatrixProfile,
    ModelProvenance,
    PlantPartDetection,
    SourceIdentity,
)


class SourceIdentityRequest(BaseModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content_hash: str = Field(min_length=32)
    canonical_uri: str | None = None

    def contract(self) -> SourceIdentity:
        return SourceIdentity(**self.model_dump())


class EvidenceSpanRequest(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    def contract(self) -> EvidenceSpan:
        return EvidenceSpan(**self.model_dump())


class LiteratureValidationRequest(BaseModel):
    claim_id: str = Field(min_length=1)
    source: SourceIdentityRequest
    evidence_spans: list[EvidenceSpanRequest] = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_value: str = Field(min_length=1)
    canonical_taxon_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    contradictions: list[str] = Field(default_factory=list)

    def contract(self) -> LiteratureClaim:
        return LiteratureClaim(
            claim_id=self.claim_id,
            source=self.source.contract(),
            evidence_spans=tuple(span.contract() for span in self.evidence_spans),
            predicate=self.predicate,
            object_value=self.object_value,
            canonical_taxon_id=self.canonical_taxon_id,
            confidence=self.confidence,
            contradictions=tuple(self.contradictions),
        )


class CharacterDefinitionRequest(BaseModel):
    character_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    allowed_states: list[str] = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0.0)

    def contract(self) -> CharacterDefinition:
        return CharacterDefinition(
            character_id=self.character_id,
            label=self.label,
            allowed_states=tuple(self.allowed_states),
            weight=self.weight,
        )


class CharacterObservationRequest(BaseModel):
    character_id: str = Field(min_length=1)
    state: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: list[str] = Field(min_length=1)

    def contract(self) -> CharacterObservation:
        return CharacterObservation(
            character_id=self.character_id,
            state=self.state,
            confidence=self.confidence,
            provenance=tuple(self.provenance),
        )


class MatrixProfileRequest(BaseModel):
    taxon_id: str = Field(min_length=1)
    accepted_name: str = Field(min_length=1)
    states: dict[str, list[str]] = Field(default_factory=dict)
    provenance: list[str] = Field(min_length=1)

    def contract(self) -> MatrixProfile:
        return MatrixProfile(
            taxon_id=self.taxon_id,
            accepted_name=self.accepted_name,
            states={key: frozenset(values) for key, values in self.states.items()},
            provenance=tuple(self.provenance),
        )


class MatrixRankingRequest(BaseModel):
    definitions: list[CharacterDefinitionRequest] = Field(min_length=1)
    observations: list[CharacterObservationRequest] = Field(min_length=1)
    profiles: list[MatrixProfileRequest] = Field(min_length=1)

    def contracts(self) -> tuple[
        dict[str, CharacterDefinition],
        tuple[CharacterObservation, ...],
        tuple[MatrixProfile, ...],
    ]:
        definitions = {item.character_id: item.contract() for item in self.definitions}
        if len(definitions) != len(self.definitions):
            raise ValueError("DUPLICATE_CHARACTER_DEFINITION")
        return (
            definitions,
            tuple(item.contract() for item in self.observations),
            tuple(item.contract() for item in self.profiles),
        )


class ModelProvenanceRequest(BaseModel):
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    inference_id: str = Field(min_length=1)

    def contract(self) -> ModelProvenance:
        return ModelProvenance(**self.model_dump())


class PlantPartDetectionRequest(BaseModel):
    part: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    def contract(self) -> PlantPartDetection:
        return PlantPartDetection(**self.model_dump())


class VisionAnalysisRequest(BaseModel):
    image_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=32)
    license_code: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    model: ModelProvenanceRequest
    detected_parts: list[PlantPartDetectionRequest] = Field(min_length=1)
    character_observations: list[CharacterObservationRequest] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def contract(self) -> ImageAnalysisResult:
        return ImageAnalysisResult(
            image_id=self.image_id,
            content_hash=self.content_hash,
            license_code=self.license_code,
            attribution=self.attribution,
            model=self.model.contract(),
            detected_parts=tuple(item.contract() for item in self.detected_parts),
            character_observations=tuple(item.contract() for item in self.character_observations),
            warnings=tuple(self.warnings),
        )


class IntegratedIdentificationRequest(BaseModel):
    analysis: VisionAnalysisRequest
    definitions: list[CharacterDefinitionRequest] = Field(min_length=1)
    profiles: list[MatrixProfileRequest] = Field(min_length=1)
    minimum_margin: float = Field(default=0.15, ge=0.0, le=1.0)

    def contracts(self) -> tuple[
        ImageAnalysisResult,
        dict[str, CharacterDefinition],
        tuple[MatrixProfile, ...],
        float,
    ]:
        definitions = {item.character_id: item.contract() for item in self.definitions}
        if len(definitions) != len(self.definitions):
            raise ValueError("DUPLICATE_CHARACTER_DEFINITION")
        return (
            self.analysis.contract(),
            definitions,
            tuple(item.contract() for item in self.profiles),
            self.minimum_margin,
        )
