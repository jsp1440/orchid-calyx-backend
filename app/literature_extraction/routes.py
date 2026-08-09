from __future__ import annotations

import os
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .candidate_handoff import (
    LiteratureCandidateHandoffError,
    LiteratureCandidateHandoffService,
    LiteratureSourceBinding,
)
from .repository import LiteratureResultRepository
from .source_binding import (
    CanonicalLiteratureSourceBinding,
    FileLiteratureSourceBindingRepository,
    LiteratureSourceBindingError,
)
from .source_binding_postgres import PostgresLiteratureSourceBindingResolver


def get_literature_repository() -> LiteratureResultRepository:
    return LiteratureResultRepository(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )


def get_source_binding_repository() -> FileLiteratureSourceBindingRepository:
    return FileLiteratureSourceBindingRepository(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )


def _transactional_source_binding_resolver() -> PostgresLiteratureSourceBindingResolver:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise LiteratureSourceBindingError("SOURCE_BINDING_DATABASE_UNAVAILABLE")
    return PostgresLiteratureSourceBindingResolver(
        lambda: psycopg.connect(database_url)
    )


def get_candidate_handoff_service() -> LiteratureCandidateHandoffService:
    from app.candidate_knowledge.dependencies import get_candidate_components

    repository, service = get_candidate_components()
    return LiteratureCandidateHandoffService(service, repository)


router = APIRouter(
    prefix="/api/literature-extraction",
    tags=["literature-extraction"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


class SourceBindingIn(BaseModel):
    source_object_type: str = Field(min_length=1)
    source_object_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    extraction_run_id: int = Field(gt=0)
    anchor_ids: dict[str, int] = Field(min_length=1)
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"


class TransactionalSourceBindingResolveIn(BaseModel):
    actor: str = Field(min_length=1)
    tenant_id: str | None = None
    project_id: str | None = None


class CandidateHandoffIn(BaseModel):
    use_persisted_binding: bool = True
    use_transactional_binding: bool = False
    source_binding: SourceBindingIn | None = None


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


@router.post("/papers/{paper_id}/source-binding/resolve")
def resolve_source_binding(
    paper_id: str,
    payload: TransactionalSourceBindingResolveIn,
    literature_repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
):
    paper = literature_repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        result = _transactional_source_binding_resolver().resolve(
            paper,
            actor=payload.actor,
            tenant_id=payload.tenant_id,
            project_id=payload.project_id,
        )
        return {
            **result.binding.to_dict(),
            "binding_id": result.binding_id,
            "created": result.created,
            "persistence": "postgresql",
        }
    except LiteratureSourceBindingError as exc:
        status_code = 503 if exc.code == "SOURCE_BINDING_DATABASE_UNAVAILABLE" else 409
        if exc.code in {
            "SOURCE_BINDING_NOT_FOUND",
            "EXTRACTION_RUN_MISMATCH",
            "ANCHOR_BINDING_NOT_FOUND",
        }:
            status_code = 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "details": exc.details},
        ) from exc


@router.put("/papers/{paper_id}/source-binding")
def create_source_binding(
    paper_id: str,
    payload: SourceBindingIn,
    response: Response,
    literature_repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
    binding_repository: Annotated[
        FileLiteratureSourceBindingRepository,
        Depends(get_source_binding_repository),
    ],
):
    paper = literature_repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        binding = CanonicalLiteratureSourceBinding(
            paper_id=paper_id, **payload.model_dump()
        )
        binding.validate_against_paper(paper)
        stored, created = binding_repository.create(binding)
        response.status_code = 201 if created else 200
        return {**stored.to_dict(), "created": created}
    except LiteratureSourceBindingError as exc:
        raise HTTPException(
            status_code=409 if exc.code == "CONFLICTING_SOURCE_REBIND" else 422,
            detail={"code": exc.code, "details": exc.details},
        ) from exc


@router.get("/papers/{paper_id}/source-binding")
def get_source_binding(
    paper_id: str,
    binding_repository: Annotated[
        FileLiteratureSourceBindingRepository,
        Depends(get_source_binding_repository),
    ],
):
    try:
        binding = binding_repository.get(paper_id)
    except LiteratureSourceBindingError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "details": exc.details}
        ) from exc
    if binding is None:
        raise HTTPException(status_code=404, detail="Canonical source binding not found")
    return binding.to_dict()


@router.post("/papers/{paper_id}/candidate-handoff", status_code=201)
def handoff_candidates(
    paper_id: str,
    payload: CandidateHandoffIn,
    literature_repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
    binding_repository: Annotated[
        FileLiteratureSourceBindingRepository,
        Depends(get_source_binding_repository),
    ],
    service: Annotated[
        LiteratureCandidateHandoffService, Depends(get_candidate_handoff_service)
    ],
):
    paper = literature_repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        persisted = binding_repository.get(paper_id)
        if payload.use_transactional_binding:
            canonical = _transactional_source_binding_resolver().get(
                paper_id, paper.analysis_manifest.analysis_id
            )
            if canonical is None:
                raise LiteratureSourceBindingError("SOURCE_BINDING_NOT_FOUND")
        elif payload.use_persisted_binding:
            if persisted is None:
                raise LiteratureSourceBindingError("CANONICAL_SOURCE_BINDING_NOT_FOUND")
            canonical = persisted
        else:
            if payload.source_binding is None:
                raise LiteratureSourceBindingError("CANONICAL_SOURCE_BINDING_REQUIRED")
            canonical = CanonicalLiteratureSourceBinding(
                paper_id=paper_id, **payload.source_binding.model_dump()
            )
            if persisted is not None and persisted.fingerprint != canonical.fingerprint:
                raise LiteratureSourceBindingError("PERSISTED_BINDING_IS_AUTHORITATIVE")
        canonical.validate_against_paper(paper)
        binding = LiteratureSourceBinding(
            source_object_type=canonical.source_object_type,
            source_object_id=canonical.source_object_id,
            revision_id=canonical.revision_id,
            extraction_run_id=canonical.extraction_run_id,
            anchor_ids=canonical.anchor_ids,
            display_policy=canonical.display_policy,
            internal_use_permission=canonical.internal_use_permission,
            language=canonical.language,
        )
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
    except LiteratureSourceBindingError as exc:
        if exc.code == "SOURCE_BINDING_DATABASE_UNAVAILABLE":
            status_code = 503
        elif exc.code in {
            "CONFLICTING_SOURCE_REBIND",
            "PERSISTED_BINDING_IS_AUTHORITATIVE",
            "BINDING_CONFLICT_REQUIRES_REVIEW",
            "CROSS_TENANT_BINDING_FORBIDDEN",
        }:
            status_code = 409
        else:
            status_code = 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "details": exc.details},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
