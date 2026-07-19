from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

OntologyKind = Literal["TAXONOMY", "GLOSSARY", "TRAIT", "HABITAT", "POLLINATOR", "MYCORRHIZA", "GEOGRAPHY", "ORGANIZATION", "PERSON", "LITERATURE", "MEDIA", "CONSERVATION"]


class RegistryCreate(BaseModel):
    namespace: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    authority: str = Field(min_length=1, max_length=500)
    source_uri: HttpUrl | None = None
    version: str = Field(min_length=1, max_length=100)
    ontology_type: OntologyKind
    checksum: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    provenance: dict[str, Any]
    created_by: str = Field(min_length=1, max_length=200)


class RegistryPatch(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    authority: str | None = Field(default=None, min_length=1, max_length=500)
    source_uri: HttpUrl | None = None
    provenance: dict[str, Any] | None = None


class ActorReason(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


class TermCreate(BaseModel):
    registry_id: int = Field(gt=0)
    canonical_key: str = Field(min_length=1, max_length=500)
    preferred_label: str = Field(min_length=1, max_length=1000)
    definition: str | None = None
    term_type: str = Field(min_length=1, max_length=100)
    parent_term_id: int | None = Field(default=None, gt=0)
    external_ids: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(min_length=1, max_length=200)


class TermPatch(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    preferred_label: str | None = Field(default=None, min_length=1, max_length=1000)
    definition: str | None = None
    parent_term_id: int | None = Field(default=None, gt=0)
    external_ids: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    replacement_term_id: int | None = Field(default=None, gt=0)
    status: Literal["DRAFT", "ACTIVE", "DEPRECATED"] | None = None


class SynonymCreate(BaseModel):
    synonym: str = Field(min_length=1, max_length=1000)
    synonym_type: Literal["EXACT", "ALTERNATE", "HISTORICAL", "ABBREVIATION", "MISSPELLING", "SCIENTIFIC_NAME", "COMMON_NAME"]
    provenance: dict[str, Any]
    actor: str = Field(min_length=1, max_length=200)


class ResolveRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    fuzzy_threshold: float = Field(default=0.88, ge=0.75, le=1)


class ManualResolution(BaseModel):
    candidate_id: int = Field(gt=0)
    ontology_term_id: int = Field(gt=0)
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


class ResolutionPatch(BaseModel):
    status: Literal["ACCEPTED", "REJECTED", "NEEDS_REVIEW"]
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


class EvidenceAction(BaseModel):
    actor: str = Field(min_length=1, max_length=200)


class ReadinessAction(BaseModel):
    actor: str = Field(min_length=1, max_length=200)


class UnresolvedRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


class TermSearch(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    registry_id: int | None = Field(default=None, gt=0)


class DeprecateTerm(BaseModel):
    actor: str
    reason: str
    replacement_term_id: int = Field(gt=0)

    @model_validator(mode="after")
    def replacement_is_present(self) -> "DeprecateTerm":
        if not self.reason.strip():
            raise ValueError("reason is required")
        return self
