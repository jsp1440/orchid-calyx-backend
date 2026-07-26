from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .candidate_handoff import (
    LiteratureCandidateHandoffError,
    LiteratureCandidateHandoffService,
    LiteratureSourceBinding,
)
from .repository import LiteratureResultRepository


def get_literature_repository() -> LiteratureResultRepository:
    return LiteratureResultRepository(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )


def get_candidate_handoff_service() -> LiteratureCandidateHandoffService:
    from app.candidate_knowledge.routes import _available

    repository, service = _available()
    return LiteratureCandidateHandoffService(service, repository)


router = APIRouter(
    prefix="/api/literature-extraction",
    tags=["literature-extraction"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


class CandidateHandoffIn(BaseModel):
    source_object_type: str = Field(min_length=1)
    source_object_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    extraction_run_id: int = Field(gt=0)
    anchor_ids: dict[str, int] = Field(min_length=1)
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"


@router.get("/papers/{paper_id}")
def get_paper(
    paper_id: str,
    repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
):
    paper = repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    return paper


@router.post("/papers/{paper_id}/candidate-handoff", status_code=201)
def handoff_candidates(
    paper_id: str,
    payload: CandidateHandoffIn,
    repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
    service: Annotated[
        LiteratureCandidateHandoffService, Depends(get_candidate_handoff_service)
    ],
):
    paper = repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        binding = LiteratureSourceBinding(**payload.model_dump())
        operation = lambda: service.handoff(paper, binding)
        candidate_repository = service.candidate_repository
        return (
            candidate_repository.atomic(operation)
            if hasattr(candidate_repository, "atomic")
            else operation()
        )
    except LiteratureCandidateHandoffError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "blocked_records": [
                    {
                        "record_id": item.record_id,
                        "code": item.code,
                        "details": item.details,
                    }
                    for item in exc.blocked
                ],
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
