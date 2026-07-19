from typing import Any, Literal

from pydantic import BaseModel, Field


class MissionCreate(BaseModel):
    mission_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=2000)
    mission_type: str = Field(min_length=1, max_length=100)
    requested_by: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=50, ge=0, le=100)
    schedule_type: Literal["manual", "scheduled", "recurring"] = "manual"
    scheduled_at: str | None = None
    recurrence_rule: str | None = None
    maximum_runs: int | None = Field(default=1, gt=0)
    maximum_failures: int = Field(default=3, ge=0)
    input_manifest: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    target_services: list[str] = Field(default_factory=list)
    target_domains: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=300)
    created_from_template_id: int | None = Field(default=None, gt=0)


class MissionPatch(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    priority: int | None = Field(default=None, ge=0, le=100)
    input_manifest: dict[str, Any] | None = None
    allowed_actions: list[str] | None = None
    prohibited_actions: list[str] | None = None


class ActorReason(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    approval_reference: str | None = Field(default=None, max_length=500)
    publication_authority: str | None = Field(default=None, max_length=500)


class CycleRequest(BaseModel):
    worker_id: str = Field(default="api-runtime-cycle", min_length=1, max_length=200)
    limit: int = Field(default=1, ge=1, le=10)
