from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ActionType = Literal[
    "TASK", "CALENDAR", "GRANT", "TAXONOMY_REVIEW", "LITERATURE_EXTRACTION",
    "PARTNERSHIP", "CONNECTOR_REVIEW", "MEDIA_SEARCH", "ARCHIVE",
]
Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ActionStatus = Literal["OPEN", "IN_PROGRESS", "WAITING", "COMPLETED", "CANCELLED"]


class RouteActionRequest(BaseModel):
    action_type: ActionType
    destination: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    owner: str | None = None
    priority: Priority = "MEDIUM"
    due_at: datetime | None = None
    reminder_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class ActionUpdateRequest(BaseModel):
    status: ActionStatus
    notes: str | None = None
    actor: str | None = None
