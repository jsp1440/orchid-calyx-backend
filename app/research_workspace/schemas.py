from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectCreate(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=10_000)
    research_question: str | None = Field(default=None, max_length=5_000)
    hypothesis: str | None = Field(default=None, max_length=5_000)
    status: Literal["ACTIVE", "PAUSED", "COMPLETED"] = "ACTIVE"


class ProjectPatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10_000)
    research_question: str | None = Field(default=None, max_length=5_000)
    hypothesis: str | None = Field(default=None, max_length=5_000)
    status: Literal["ACTIVE", "PAUSED", "COMPLETED"] | None = None
    expected_version: int = Field(gt=0)


class SavedSearchCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    query: dict[str, Any]
    result_count_snapshot: int | None = Field(default=None, ge=0)

    @field_validator("query")
    @classmethod
    def bounded_query(cls, value: dict[str, Any]):
        import json

        if len(json.dumps(value, separators=(",", ":"))) > 20_000:
            raise ValueError("query is too large")
        return value


class NoteCreate(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=50_000)
    note_type: Literal["GENERAL", "QUESTION", "METHOD", "OBSERVATION"] = "GENERAL"


class TaxonLinkCreate(StrictModel):
    taxon_id: str = Field(min_length=1, max_length=300)
    relationship: Literal["SUBJECT", "COMPARISON", "CONTEXT", "EXCLUDED"] = "SUBJECT"


class DocumentLinkCreate(StrictModel):
    document_id: str = Field(min_length=1, max_length=300)
    revision_id: str | None = Field(default=None, max_length=300)
    relationship: Literal["SOURCE", "BACKGROUND", "METHOD", "CONTRADICTS"] = "SOURCE"


class EvidenceLinkCreate(StrictModel):
    evidence_kind: Literal["CANDIDATE", "AGGREGATE"]
    evidence_id: str = Field(min_length=1, max_length=300)
    relationship: Literal["SUPPORTS", "CONTRADICTS", "CONTEXT", "REVIEW"] = "SUPPORTS"
