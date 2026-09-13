from __future__ import annotations

import os
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .candidate_handoff import (
    LiteratureCandidateHandoffError,
    LiteratureCandidateHandoffService,
    LiteratureSourceBinding,
)
from .canonical_binding_resolver import (
    BindingScope,
    DocumentIntelligenceBindingResolver,
    PostgresLiteratureSourceBindingRepository,
)
from .coverage_audit import audit_literature_extraction_coverage
from .repository import LiteratureResultRepository
from .source_binding import (
    CanonicalLiteratureSourceBinding,
    FileLiteratureSourceBindingRepository,
    LiteratureSourceBindingError,
)


def get_literature_repository() -> LiteratureResultRepository:
    return LiteratureResultRepository(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )


def get_source_binding_repository() -> FileLiteratureSourceBindingRepository:
    return FileLiteratureSourceBindingRepository(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
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


class CandidateHandoffIn(BaseModel):
    use_persisted_binding: bool = True
    source_binding: SourceBindingIn | None = None


class CanonicalBindingResolveIn(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)


def _raw_source_or_error(
    repository: LiteratureResultRepository, paper_id: str
) -> bytes:
    raw_bytes = repository.get_raw_bytes(paper_id)
    if raw_bytes is None:
        raise LiteratureSourceBindingError(
            "RAW_SOURCE_NOT_FOUND", {"paper_id": paper_id}
        )
    return raw_bytes


def _database_url_or_error() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=503,
            detail={"code": "CANONICAL_BINDING_PERSISTENCE_UNAVAILABLE"},
        )
    return database_url


def _scope(auth_context: dict[str, object], project_id: str) -> BindingScope:
    actor = str(auth_context.get("actor") or "").strip()
    return BindingScope(owner_id=actor, project_id=project_id)


def _candidate_binding(canonical: CanonicalLiteratureSourceBinding) -> LiteratureSourceBinding:
    return LiteratureSourceBinding(
        source_object_type=canonical.source_object_type,
        source_object_id=canonical.source_object_id,
        revision_id=canonical.revision_id,
        extraction_run_id=canonical.extraction_run_id,
        anchor_ids=canonical.anchor_ids,
        display_policy=canonical.display_policy,
        internal_use_permission=canonical.internal_use_permission,
        language=canonical.language,
        evidence_integrity=canonical.evidence_integrity,
    )


def _execute_candidate_handoff(
    paper: Any,
    canonical: CanonicalLiteratureSourceBinding,
    service: LiteratureCandidateHandoffService,
):
    operation = lambda: service.handoff(paper, _candidate_binding(canonical))
    candidate_repository = service.candidate_repository
    return (
        candidate_repository.atomic(operation)
        if hasattr(candidate_repository, "atomic")
        else operation()
    )


def _source_binding_http_error(exc: LiteratureSourceBindingError) -> HTTPException:
    conflict_codes = {
        "CONFLICTING_SOURCE_REBIND",
        "PERSISTED_BINDING_IS_AUTHORITATIVE",
        "BINDING_CONFLICT_REQUIRES_REVIEW",
        "SOURCE_BINDING_AMBIGUOUS",
        "SOURCE_OBJECT_BINDING_AMBIGUOUS",
        "EXTRACTION_RUN_AMBIGUOUS",
        "ANCHOR_BINDING_AMBIGUOUS",
    }
    return HTTPException(
        status_code=409 if exc.code in conflict_codes else 422,
        detail={"code": exc.code, "details": exc.details},
    )


def _candidate_handoff_http_error(exc: LiteratureCandidateHandoffError) -> HTTPException:
    return HTTPException(
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
    )


@router.get("/coverage-audit")
def literature_extraction_coverage_audit(
    repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return audit_literature_extraction_coverage(None, repository)
    try:
        with (
            psycopg.connect(database_url, connect_timeout=5) as conn,
            conn.cursor() as cur,
        ):
            return audit_literature_extraction_coverage(cur, repository)
    except Exception as exc:  # noqa: BLE001 - telemetry must fail closed on DB errors
        return audit_literature_extraction_coverage(
            None,
            repository,
            db_unavailable_detail=f"Database telemetry unavailable: {exc}",
        )


@router.get("/papers")
def list_papers(
    repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
    limit: int = 50,
    offset: int = 0,
):
    if limit < 1 or offset < 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_PAGE_BOUNDS",
                "message": "limit must be >= 1 and offset >= 0",
            },
        )
    summaries, total = repository.list_summaries(limit=limit, offset=offset)
    return {
        "papers": summaries,
        "total": total,
        "limit": limit,
        "offset": offset,
        "unreadable_count": sum(
            1 for item in summaries if not item.get("readable", False)
        ),
    }


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
    """Legacy explicit binding path retained for compatibility.

    New operational callers should use ``source-binding/resolve`` so canonical
    IDs come from Document Intelligence rather than request JSON.
    """
    paper = literature_repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        binding = CanonicalLiteratureSourceBinding(
            paper_id=paper_id, **payload.model_dump()
        ).with_verified_integrity(
            paper, _raw_source_or_error(literature_repository, paper_id)
        )
        stored, created = binding_repository.create(binding)
        response.status_code = 201 if created else 200
        return {**stored.to_dict(), "created": created, "exact_source_integrity": True}
    except LiteratureSourceBindingError as exc:
        raise _source_binding_http_error(exc) from exc


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
        raise _source_binding_http_error(exc) from exc
    if binding is None:
        raise HTTPException(status_code=404, detail="Canonical source binding not found")
    return binding.to_dict()


@router.post("/papers/{paper_id}/source-binding/resolve")
def resolve_canonical_source_binding(
    paper_id: str,
    payload: CanonicalBindingResolveIn,
    literature_repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
    auth_context: Annotated[dict[str, object], Depends(verify_owner_or_api_key)],
):
    """Resolve and persist exact canonical identities without caller-supplied IDs."""
    paper = literature_repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        raw_bytes = _raw_source_or_error(literature_repository, paper_id)
        with psycopg.connect(
            _database_url_or_error(), connect_timeout=5, autocommit=False
        ) as conn, conn.cursor() as cur:
            resolved, created = PostgresLiteratureSourceBindingRepository().resolve_and_create(
                cur,
                resolver=DocumentIntelligenceBindingResolver(),
                scope=_scope(auth_context, payload.project_id),
                paper=paper,
                raw_bytes=raw_bytes,
            )
        return {
            **resolved.binding.to_dict(),
            "analysis_id": resolved.analysis_id,
            "record_id": resolved.record_id,
            "created": created,
            "exact_source_integrity": True,
            "resolution_mode": "canonical_document_intelligence",
        }
    except LiteratureSourceBindingError as exc:
        raise _source_binding_http_error(exc) from exc
    except psycopg.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "CANONICAL_BINDING_PERSISTENCE_UNAVAILABLE"},
        ) from exc


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
    """Legacy candidate handoff using the file binding contract."""
    paper = literature_repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        raw_bytes = _raw_source_or_error(literature_repository, paper_id)
        persisted = binding_repository.get(paper_id)
        if payload.use_persisted_binding:
            if persisted is None:
                raise LiteratureSourceBindingError("CANONICAL_SOURCE_BINDING_NOT_FOUND")
            canonical = persisted
        else:
            if payload.source_binding is None:
                raise LiteratureSourceBindingError("CANONICAL_SOURCE_BINDING_REQUIRED")
            canonical = CanonicalLiteratureSourceBinding(
                paper_id=paper_id, **payload.source_binding.model_dump()
            ).with_verified_integrity(paper, raw_bytes)
            if persisted is not None and persisted.fingerprint != canonical.fingerprint:
                raise LiteratureSourceBindingError("PERSISTED_BINDING_IS_AUTHORITATIVE")
        canonical.validate_integrity(paper, raw_bytes)
        return _execute_candidate_handoff(paper, canonical, service)
    except LiteratureCandidateHandoffError as exc:
        raise _candidate_handoff_http_error(exc) from exc
    except LiteratureSourceBindingError as exc:
        raise _source_binding_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.post("/papers/{paper_id}/candidate-handoff/canonical", status_code=201)
def handoff_candidates_from_canonical_document_intelligence(
    paper_id: str,
    payload: CanonicalBindingResolveIn,
    literature_repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
    service: Annotated[
        LiteratureCandidateHandoffService, Depends(get_candidate_handoff_service)
    ],
    auth_context: Annotated[dict[str, object], Depends(verify_owner_or_api_key)],
):
    """Operational evidence -> canonical identity -> unpublished candidate path."""
    paper = literature_repository.get(paper_id)
    if paper is None:
        raise HTTPException(
            status_code=404, detail="Literature extraction result not found"
        )
    try:
        raw_bytes = _raw_source_or_error(literature_repository, paper_id)
        with psycopg.connect(
            _database_url_or_error(), connect_timeout=5, autocommit=False
        ) as conn, conn.cursor() as cur:
            resolved, _ = PostgresLiteratureSourceBindingRepository().resolve_and_create(
                cur,
                resolver=DocumentIntelligenceBindingResolver(),
                scope=_scope(auth_context, payload.project_id),
                paper=paper,
                raw_bytes=raw_bytes,
            )
        resolved.binding.validate_integrity(paper, raw_bytes)
        result = _execute_candidate_handoff(paper, resolved.binding, service)
        if isinstance(result, dict):
            return {
                **result,
                "canonical_source_binding": {
                    "record_id": resolved.record_id,
                    "analysis_id": resolved.analysis_id,
                    "binding_fingerprint": resolved.binding.fingerprint,
                },
            }
        return result
    except LiteratureCandidateHandoffError as exc:
        raise _candidate_handoff_http_error(exc) from exc
    except LiteratureSourceBindingError as exc:
        raise _source_binding_http_error(exc) from exc
    except psycopg.Error as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "CANONICAL_BINDING_PERSISTENCE_UNAVAILABLE"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
