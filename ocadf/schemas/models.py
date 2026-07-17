"""Versioned core records for BUILD-070.

These models are intentionally vendor-neutral and contain no runtime or
production-database dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, root_validator, validator

SCHEMA_VERSION = "1.0"


class StrictModel(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSION)

    class Config:
        extra = "forbid"
        validate_assignment = True

    @validator("schema_version")
    def supported_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {value}")
        return value


class ProjectStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    active = "active"
    blocked = "blocked"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskStatus(str, Enum):
    pending = "pending"
    ready = "ready"
    claimed = "claimed"
    running = "running"
    validating = "validating"
    blocked = "blocked"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"


class GateLevel(str, Enum):
    level_0 = "level_0"
    level_1 = "level_1"
    level_2 = "level_2"
    level_3 = "level_3"


class ValidationOutcome(str, Enum):
    passed = "passed"
    failed = "failed"
    needs_review = "needs_review"


class SourceReference(StrictModel):
    repository: str
    path: str
    revision: str
    content_hash: str

    @validator("repository", "path", "revision", "content_hash")
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class ApprovalGate(StrictModel):
    gate_id: str
    level: GateLevel
    reason: str
    required_approver_role: str
    status: str = "pending"
    bundled_questions: List[str] = Field(default_factory=list)
    decision_id: Optional[str] = None


class TaskRecord(StrictModel):
    task_id: str
    project_id: str
    title: str
    objective: str
    role: str
    status: TaskStatus = TaskStatus.pending
    depends_on: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    gate: GateLevel = GateLevel.level_1
    source: Optional[SourceReference] = None

    @root_validator
    def no_self_dependency(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        task_id = values.get("task_id")
        if task_id and task_id in values.get("depends_on", []):
            raise ValueError("task cannot depend on itself")
        return values


class ProjectRecord(StrictModel):
    project_id: str
    title: str
    mission: str
    owner_role: str
    status: ProjectStatus = ProjectStatus.proposed
    priority: str
    dependencies: List[str] = Field(default_factory=list)
    task_ids: List[str] = Field(default_factory=list)
    source: Optional[SourceReference] = None


class ValidationRecord(StrictModel):
    validation_id: str
    project_id: str
    task_id: str
    validator_id: str
    author_worker_id: str
    outcome: ValidationOutcome
    evidence: List[str] = Field(default_factory=list)
    defects: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @root_validator
    def validator_must_be_independent(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get("validator_id") == values.get("author_worker_id"):
            raise ValueError("validator must differ from authoring worker")
        return values


class DecisionRecord(StrictModel):
    decision_id: str
    project_id: str
    title: str
    decision: str
    rationale: str
    approver_role: str
    alternatives: List[str] = Field(default_factory=list)
    consequences: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EventRecord(StrictModel):
    event_id: str
    project_id: str
    event_type: str
    actor_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LessonRecord(StrictModel):
    lesson_id: str
    project_id: str
    task_id: Optional[str] = None
    summary: str
    successful: bool
    cause: str
    reusable_guidance: str
    evidence: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
