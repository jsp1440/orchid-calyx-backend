from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .reasoning import InferenceType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InferRequest(StrictModel):
    subject_node_id: int = Field(gt=0)
    inference_type: InferenceType
    limit: int = Field(default=25, ge=1, le=100)


class GraphQuery(StrictModel):
    node_type: str | None = Field(default=None, min_length=1, max_length=100)
    edge_type: str | None = Field(default=None, min_length=1, max_length=100)
    canonical_key: str | None = Field(default=None, min_length=1, max_length=500)
    limit: int = Field(default=50, ge=1, le=100)


class ConnectRequest(StrictModel):
    connector_id: str = Field(min_length=1, max_length=100)
    action: Literal["describe", "health"]
    payload: dict[str, Any] = Field(default_factory=dict)
