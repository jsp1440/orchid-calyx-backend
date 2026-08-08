from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .reasoning import InferenceType
from .reasoning_map import ReasoningDirection, ReasoningProfile


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InferRequest(StrictModel):
    subject_node_id: int = Field(gt=0)
    inference_type: InferenceType
    limit: int = Field(default=25, ge=1, le=100)


class ReasoningMapRequest(StrictModel):
    subject_node_id: int = Field(gt=0)
    direction: ReasoningDirection = ReasoningDirection.FORWARD
    profile: ReasoningProfile = ReasoningProfile.ALL_RELATIONSHIPS
    max_depth: int = Field(default=4, ge=1, le=8)
    limit: int = Field(default=200, ge=1, le=1000)
    edge_types: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    causal_only: bool = False


class GraphQuery(StrictModel):
    node_type: str | None = Field(default=None, min_length=1, max_length=100)
    edge_type: str | None = Field(default=None, min_length=1, max_length=100)
    canonical_key: str | None = Field(default=None, min_length=1, max_length=500)
    limit: int = Field(default=50, ge=1, le=100)


class ConnectRequest(StrictModel):
    connector_id: str = Field(min_length=1, max_length=100)
    action: Literal["describe", "health"]
    payload: dict[str, Any] = Field(default_factory=dict)


class InferenceLedgerSubmission(StrictModel):
    ledger_id: UUID
    project_id: UUID
    expected_version: int = Field(ge=1)
    inference_type: InferenceType
    candidate_node_id: int = Field(gt=0)
    inference_content_hash: str = Field(pattern="^[0-9a-f]{64}$")
