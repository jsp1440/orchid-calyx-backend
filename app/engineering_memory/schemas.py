"""Pydantic request/response schemas for the engineering-memory API.

All request models set ``extra="forbid"``.  This is a governance control, not
just hygiene: it guarantees that unmodelled fields such as ``raw_prompt`` or
``conversation`` are rejected, so raw prompts/conversations cannot be stored by
default.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunCreateIn(_Strict):
    executor: str = Field(min_length=1, max_length=80)
    provider: str | None = Field(default=None, max_length=120)
    workspace_scope: str = Field(min_length=1, max_length=240)
    repository: str = Field(min_length=1, max_length=240)
    branch: str | None = Field(default=None, max_length=240)
    task_ref: str | None = Field(default=None, max_length=240)
    issue_ref: str | None = Field(default=None, max_length=120)
    pr_ref: str | None = Field(default=None, max_length=120)
    commit_shas: list[str] = Field(default_factory=list, max_length=50)
    outcome: str = Field(pattern=r"^(success|failure|partial)$")
    checks: dict[str, Any] = Field(default_factory=dict)
    sanitized_summary: str = Field(default="", max_length=20000)
    tokens_input: int | None = Field(default=None, ge=0)
    tokens_output: int | None = Field(default=None, ge=0)
    turns: int | None = Field(default=None, ge=0)
    elapsed_ms: int | None = Field(default=None, ge=0)
    data_classification: str = Field(min_length=1, max_length=40)
    evidence_class: str | None = Field(default=None, max_length=40)
    strict_locality: bool = False


class LessonCreateIn(_Strict):
    workspace_scope: str = Field(min_length=1, max_length=240)
    repository: str = Field(min_length=1, max_length=240)
    module: str | None = Field(default=None, max_length=240)
    problem: str = Field(min_length=1, max_length=20000)
    cause: str = Field(default="", max_length=20000)
    solution: str = Field(min_length=1, max_length=20000)
    applicability: str = Field(default="", max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    source_run_id: str | None = Field(default=None, max_length=36)
    github_provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: str = Field(default="low", pattern=r"^(low|medium|high)$")
    data_classification: str = Field(min_length=1, max_length=40)
    evidence_class: str | None = Field(default=None, max_length=40)
    dependencies: dict[str, str] | None = None
    schema_marker: str | None = Field(default=None, max_length=240)
    files: dict[str, str] | None = None
    embedding: list[float] | None = None
    expires_at: str | None = None
    strict_locality: bool = False


class LessonVerifyIn(_Strict):
    workspace_scope: str = Field(min_length=1, max_length=240)
    evidence: dict[str, Any] = Field(min_length=1)


class LessonInvalidateIn(_Strict):
    workspace_scope: str = Field(min_length=1, max_length=240)
    reason: str = Field(default="", max_length=240)


class RetrieveIn(_Strict):
    workspace_scope: str = Field(min_length=1, max_length=240)
    repository: str = Field(default="", max_length=240)
    module: str | None = Field(default=None, max_length=240)
    query: str = Field(min_length=1, max_length=8000)
    limit: int = Field(default=5, ge=1, le=5)
    char_budget: int = Field(default=4000, ge=200, le=32000)
    injected: bool = False


class FeedbackIn(_Strict):
    workspace_scope: str = Field(min_length=1, max_length=240)
    feedback: str = Field(pattern=r"^(helpful|not_helpful|unused)$")
    injected: bool = False
    outcome: dict[str, Any] | None = None
    estimated_tokens_saved: int | None = Field(default=None, ge=0)
