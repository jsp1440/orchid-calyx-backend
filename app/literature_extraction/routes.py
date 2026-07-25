from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.security import verify_owner_or_api_key

from .repository import LiteratureResultRepository


def get_literature_repository() -> LiteratureResultRepository:
    return LiteratureResultRepository(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )


router = APIRouter(
    prefix="/api/literature-extraction",
    tags=["literature-extraction"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


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
