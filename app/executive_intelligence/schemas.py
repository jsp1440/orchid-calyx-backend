from typing import Any, Literal

from pydantic import BaseModel, Field

Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
BudgetDecision = Literal["ALLOW", "WARN", "DOWNGRADE", "BLOCK"]
RecommendationStatus = Literal["PENDING", "APPROVED", "REJECTED", "ROUTED"]


class RecommendationGenerateRequest(BaseModel):
    workspace_id: str = Field(default="default", min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=120)
    actor: str | None = Field(default=None, max_length=200)


class RecommendationDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    actor: str | None = Field(default=None, max_length=200)
    notes: str | None = None


class RecommendationRouteRequest(BaseModel):
    owner: str | None = Field(default=None, max_length=200)
    due_at: str | None = None
    reminder_at: str | None = None
    notes: str | None = None


class ProviderRouteRequest(BaseModel):
    capability: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(default="default", min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=120)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    preferred_provider: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderUpsertRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list)
    priority: int = Field(default=100, ge=0)
    cost_rank: int = Field(default=100, ge=0)
    managed: bool = True
    enabled: bool = True
    healthy: bool = True
    configuration: dict[str, Any] = Field(default_factory=dict)


class BudgetPolicyUpsertRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=120)
    provider_key: str | None = Field(default=None, max_length=120)
    soft_limit_usd: float | None = Field(default=None, ge=0)
    hard_limit_usd: float | None = Field(default=None, ge=0)
    policy_mode: Literal["WARN", "DOWNGRADE", "BLOCK"] = "WARN"
    period: Literal["DAILY", "MONTHLY", "LIFETIME"] = "MONTHLY"
    enabled: bool = True


class UsageRecordRequest(BaseModel):
    workspace_id: str = Field(default="default", min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=120)
    provider_key: str = Field(min_length=1, max_length=120)
    model_key: str = Field(min_length=1, max_length=160)
    task_type: str = Field(min_length=1, max_length=160)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    actual_cost_usd: float | None = Field(default=None, ge=0)
    input_units: int | None = Field(default=None, ge=0)
    output_units: int | None = Field(default=None, ge=0)
    workflow_action_id: int | None = Field(default=None, ge=1)
    recommendation_id: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
