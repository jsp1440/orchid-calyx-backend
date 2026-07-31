from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import LedgerEntryKind, ReviewOutcome

FORBIDDEN_PRIVATE_KEYS = {
    "chain_of_thought",
    "chain-of-thought",
    "private_cot",
    "is_private_cot",
    "hidden_reasoning",
}


def _reject_private_reasoning(value: Any) -> Any:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).casefold() in FORBIDDEN_PRIVATE_KEYS:
                raise ValueError("private model chain-of-thought is not accepted")
            _reject_private_reasoning(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_private_reasoning(nested)
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LedgerCreateIn(StrictModel):
    project_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=10_000)


class ProvenanceIn(StrictModel):
    source_kind: str = Field(min_length=1, max_length=40)
    source_id: str = Field(min_length=1, max_length=256)
    literature_record_id: str | None = Field(default=None, max_length=256)
    concept_id: str | None = Field(default=None, max_length=256)
    dataset_id: str | None = Field(default=None, max_length=256)
    method_id: str | None = Field(default=None, max_length=256)
    tool_id: str | None = Field(default=None, max_length=256)
    execution_id: str | None = Field(default=None, max_length=256)
    content_hash: str | None = Field(default=None, pattern="^[0-9a-fA-F]{64}$")
    collector: str | None = Field(default=None, max_length=256)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def no_private_reasoning(cls, value):
        return _reject_private_reasoning(value)


class UncertaintyIn(StrictModel):
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(default="", max_length=4_000)
    unresolved_assumptions: list[str] = Field(default_factory=list, max_length=100)


class LedgerEntryIn(StrictModel):
    expected_version: int = Field(ge=1)
    kind: LedgerEntryKind
    text: str = Field(min_length=1, max_length=100_000)
    provenance: ProvenanceIn | None = None
    uncertainty: UncertaintyIn | None = None
    references_entry_ids: list[str] = Field(default_factory=list, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def no_private_reasoning(cls, value):
        return _reject_private_reasoning(value)


class ExpectedVersionIn(StrictModel):
    expected_version: int = Field(ge=1)


class ConflictResolutionIn(ExpectedVersionIn):
    resolution_state: Literal["resolved", "superseded"]
    rationale: str = Field(min_length=1, max_length=4_000)


class ReviewIn(ExpectedVersionIn):
    outcome: ReviewOutcome
    rationale: str = Field(min_length=1, max_length=4_000)
