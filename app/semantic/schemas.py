from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ExtractRequest(BaseModel):
    document_id: int = Field(gt=0)
    actor: str = Field(min_length=1, max_length=200)


class CandidatePatch(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, min_length=1, max_length=1000)
    entity_type: str | None = Field(default=None, min_length=1, max_length=100)
    predicate: str | None = Field(default=None, min_length=1, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: Literal["PENDING", "ACCEPTED", "REJECTED"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "CandidatePatch":
        if not self.model_dump(exclude={"actor", "reason"}, exclude_none=True):
            raise ValueError("At least one candidate field must be supplied")
        return self


class ReviewRequest(BaseModel):
    session_id: int = Field(gt=0)
    candidate_ids: list[int] = Field(min_length=1)
    decision: Literal["ACCEPT", "REJECT", "NEEDS_REVISION"]
    actor: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_unique_candidates(self) -> "ReviewRequest":
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate_ids must be unique")
        return self


class SessionResponse(BaseModel):
    id: int
    document_id: int
    stage: str
    provenance: dict[str, Any]
