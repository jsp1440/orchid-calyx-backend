from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DataIntelligenceError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class DatasetRef(BaseModel):
    dataset_id: str = Field(min_length=8, max_length=64)
    version_id: str = Field(min_length=16, max_length=64)


class ChartSpec(BaseModel):
    kind: Literal["bar"] = "bar"
    x: str
    y: str
    title: str | None = None


class AnalysisOperation(BaseModel):
    kind: Literal[
        "select",
        "filter_equals",
        "sort",
        "limit",
        "aggregate",
        "group_aggregate",
        "pivot",
        "join",
    ]
    columns: list[str] = Field(default_factory=list)
    column: str | None = None
    value: Any = None
    descending: bool = False
    limit: int | None = Field(default=None, ge=1, le=5000)
    group_by: list[str] = Field(default_factory=list)
    aggregate_column: str | None = None
    aggregate_function: Literal["count", "sum", "mean", "min", "max"] | None = None
    pivot_index: str | None = None
    pivot_columns: str | None = None
    other_dataset: DatasetRef | None = None
    left_on: str | None = None
    right_on: str | None = None
    join_how: Literal["inner", "left"] | None = None

    @model_validator(mode="after")
    def validate_shape(self):
        if self.kind == "select" and not self.columns:
            raise ValueError("select requires columns")
        if self.kind == "filter_equals" and not self.column:
            raise ValueError("filter_equals requires column")
        if self.kind == "sort" and not self.column:
            raise ValueError("sort requires column")
        if self.kind == "limit" and self.limit is None:
            raise ValueError("limit requires limit")
        if self.kind == "aggregate" and not (
            self.aggregate_function and (self.aggregate_column or self.aggregate_function == "count")
        ):
            raise ValueError("aggregate requires function and column unless count")
        if self.kind == "group_aggregate" and not (
            self.group_by
            and self.aggregate_function
            and (self.aggregate_column or self.aggregate_function == "count")
        ):
            raise ValueError("group_aggregate requires group_by and aggregation")
        if self.kind == "pivot" and not (
            self.pivot_index
            and self.pivot_columns
            and self.aggregate_function
            and (self.aggregate_column or self.aggregate_function == "count")
        ):
            raise ValueError("pivot requires index, columns, and aggregation")
        if self.kind == "join" and not (
            self.other_dataset and self.left_on and self.right_on and self.join_how
        ):
            raise ValueError("join requires other_dataset, keys, and join_how")
        return self


class AnalysisPlan(BaseModel):
    dataset: DatasetRef
    intent: str = Field(min_length=1, max_length=1000)
    operations: list[AnalysisOperation] = Field(default_factory=list, max_length=25)
    chart: ChartSpec | None = None
    seed: int = 0

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class CompileIntentIn(BaseModel):
    dataset: DatasetRef
    intent: str = Field(min_length=1, max_length=1000)


class RerunResult(BaseModel):
    analysis_id: str
    equivalent_artifacts: bool
    previous_artifact_hashes: dict[str, str]
    current_artifact_hashes: dict[str, str]
