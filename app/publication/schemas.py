from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PublicationScope(BaseModel):
    session_id: int | None = Field(default=None, gt=0)
    candidate_ids: list[int] | None = None

    @model_validator(mode="after")
    def exactly_one_scope(self) -> "PublicationScope":
        ids = self.candidate_ids or []
        if self.session_id is None and not ids:
            raise ValueError("session_id or candidate_ids is required")
        if self.session_id is not None and ids:
            raise ValueError("provide either session_id or candidate_ids, not both")
        if len(set(ids)) != len(ids):
            raise ValueError("candidate_ids must be unique")
        return self


class PublicationRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    scope: PublicationScope
    approval_reference: str | None = Field(default=None, max_length=500)
    publication_authority: str | None = Field(default=None, max_length=500)
    dry_run_run_id: int | None = Field(default=None, gt=0)


class RollbackRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    strategy: Literal["SUPERSEDE_ONLY", "MARK_ROLLED_BACK"] = "SUPERSEDE_ONLY"


class PublicationResponse(BaseModel):
    run_id: int
    mode: Literal["DRY_RUN", "PUBLISH"]
    status: str
    manifest_digest: str
    canonical_graph_mutated: bool
    counts: dict[str, int]
    blockers: list[dict[str, Any]]
    items: list[dict[str, Any]]
