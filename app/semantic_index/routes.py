from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.persistence.state_repository import configured_database_url
from app.security import verify_owner_or_api_key

from .memory_repository import MemoryIndexRepository
from .models import IndexDocument
from .provider import DeterministicLocalProvider
from .service import SemanticIndexService

router = APIRouter(
    prefix="/api/semantic-index",
    tags=["semantic-index"],
    dependencies=[Depends(verify_owner_or_api_key)],
)
DATABASE_URL = configured_database_url()
DURABLE_MODE_CONFIGURED = bool(DATABASE_URL)
REPO = None
SERVICE = None
REPO_ERROR = None
LAST_DURABLE_REFRESH_AT = None
LAST_DURABLE_WRITE_AT = None


def _now():
    return datetime.now(UTC).isoformat()


def _build_repository():
    if DURABLE_MODE_CONFIGURED:
        from .postgres_repository import PostgresIndexRepository

        return PostgresIndexRepository(DATABASE_URL)
    return MemoryIndexRepository()


def _mark_unavailable():
    global REPO, SERVICE, REPO_ERROR
    REPO = None
    SERVICE = None
    REPO_ERROR = "SEMANTIC_INDEX_DATABASE_UNAVAILABLE"


def _activate_repository(repository):
    global REPO, SERVICE, REPO_ERROR, LAST_DURABLE_REFRESH_AT
    REPO = repository
    SERVICE = SemanticIndexService(repository, DeterministicLocalProvider())
    REPO_ERROR = None
    if DURABLE_MODE_CONFIGURED and hasattr(repository, "atomic"):
        LAST_DURABLE_REFRESH_AT = _now()


def _ensure_repository():
    if REPO is not None and SERVICE is not None:
        return REPO, SERVICE
    try:
        repository = _build_repository()
    except Exception as exc:
        if DURABLE_MODE_CONFIGURED:
            _mark_unavailable()
            raise HTTPException(503, detail={"code": REPO_ERROR}) from exc
        repository = MemoryIndexRepository()
    _activate_repository(repository)
    return REPO, SERVICE


try:
    _ensure_repository()
except HTTPException:
    pass


def _write(operation):
    global LAST_DURABLE_REFRESH_AT, LAST_DURABLE_WRITE_AT
    repository, _ = _ensure_repository()
    try:
        result = (
            repository.atomic(operation)
            if hasattr(repository, "atomic")
            else operation()
        )
        if DURABLE_MODE_CONFIGURED and hasattr(repository, "atomic"):
            LAST_DURABLE_WRITE_AT = _now()
            if hasattr(repository, "refresh_for_read"):
                repository.refresh_for_read()
            LAST_DURABLE_REFRESH_AT = _now()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        if DURABLE_MODE_CONFIGURED:
            _mark_unavailable()
            raise HTTPException(503, detail={"code": REPO_ERROR}) from exc
        raise


def _read():
    global LAST_DURABLE_REFRESH_AT
    repository, _ = _ensure_repository()
    try:
        if hasattr(repository, "refresh_for_read"):
            repository.refresh_for_read()
            if DURABLE_MODE_CONFIGURED and hasattr(repository, "atomic"):
                LAST_DURABLE_REFRESH_AT = _now()
        elif hasattr(repository, "refresh"):
            repository.refresh()
            if DURABLE_MODE_CONFIGURED and hasattr(repository, "atomic"):
                LAST_DURABLE_REFRESH_AT = _now()
        return repository
    except HTTPException:
        raise
    except Exception as exc:
        if DURABLE_MODE_CONFIGURED:
            _mark_unavailable()
            raise HTTPException(503, detail={"code": REPO_ERROR}) from exc
        raise


def get_repository_for_read():
    return _read()


def retrieval_backend_status():
    backend = "UNAVAILABLE"
    durable = False
    degraded = DURABLE_MODE_CONFIGURED and (REPO is None or SERVICE is None)
    indexed = 0
    authorized = 0
    active_models = 0
    if REPO is not None:
        backend = type(REPO).__name__
        durable = bool(hasattr(REPO, "atomic")) and not degraded
        indexed = len(REPO.documents)
        authorized = sum(
            1
            for d in REPO.documents
            if d.get("metadata", {}).get("display_policy")
            not in (None, "UNKNOWN_REQUIRES_REVIEW")
            and d.get("active", False)
        )
        active_models = len(REPO.models)
    elif not DURABLE_MODE_CONFIGURED:
        backend = "MemoryIndexRepository"
    return {
        "retrieval_backend": backend,
        "durable": durable,
        "degraded": degraded,
        "unavailable": degraded,
        "indexed_document_count": indexed,
        "display_authorized_count": authorized,
        "active_model_count": active_models,
        "index_error": REPO_ERROR,
        "last_successful_durable_refresh_at": LAST_DURABLE_REFRESH_AT,
        "last_successful_durable_write_at": LAST_DURABLE_WRITE_AT,
    }


class DocumentIn(BaseModel):
    source_object_type: str
    source_object_id: int
    revision_id: int
    extraction_run_id: int
    text: str
    parent_type: str | None = None
    parent_id: int | None = None
    source_anchor_ids: list[int] = []
    internal_indexing_permission: bool = False
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    metadata: dict[str, Any] = {}


class PreviewIn(BaseModel):
    documents: list[DocumentIn] = Field(min_length=1, max_length=500)
    configuration: dict[str, Any] = {}


@router.post("/preview", status_code=201)
def preview(p: PreviewIn):
    _, service = _ensure_repository()
    return _write(
        lambda: service.preview(
            [
                IndexDocument(
                    **{
                        **x.model_dump(),
                        "source_anchor_ids": tuple(x.source_anchor_ids),
                    }
                )
                for x in p.documents
            ],
            configuration=p.configuration,
        )
    )


@router.post("/runs/{run_id}/execute")
def execute(run_id: int):
    _, service = _ensure_repository()
    return _write(lambda: service.execute(run_id))


@router.get("/runs/{run_id}")
def status(run_id: int):
    return _read().status(run_id)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: int):
    _, service = _ensure_repository()
    return _write(lambda: service.cancel(run_id))


@router.post("/runs/{run_id}/resume")
def resume(run_id: int):
    _, service = _ensure_repository()
    return _write(lambda: service.resume(run_id))


@router.get("/history")
def history():
    return {"items": list(_read().runs.values())}


@router.get("/runs/{run_id}/items")
def items(run_id: int):
    repository = _read()
    return {"items": repository.items[run_id], "warnings": repository.warnings}


@router.get("/registry")
def registry():
    return {"models": _read().models}


@router.get("/reviews")
def reviews():
    return {"items": _read().reviews}


@router.get("/sources/{object_type}/{object_id}/versions")
def versions(object_type: str, object_id: int):
    return {
        "items": [
            x
            for x in _read().documents
            if x["source_object_type"] == object_type
            and x["source_object_id"] == object_id
        ]
    }


@router.get("/tombstones")
def tombstones():
    return {"items": _read().tombstones}
