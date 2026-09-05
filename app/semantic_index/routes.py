from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .models import IndexDocument
from .repository_runtime import get_repository_runtime

router = APIRouter(
    prefix="/api/semantic-index",
    tags=["semantic-index"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


def _runtime():
    return get_repository_runtime()


def _ensure_repository():
    return _runtime().ensure()


def _write(operation):
    return _runtime().write(operation)


def _read():
    return _runtime().read()


def get_repository_for_read():
    """Compatibility accessor for existing non-route consumers."""
    return _read()


def retrieval_backend_status():
    return _runtime().status()


try:
    _ensure_repository()
except HTTPException:
    pass


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
