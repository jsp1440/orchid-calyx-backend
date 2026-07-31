from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.archive.importer import ArchiveImporter, ImportOptions
from app.archive.registry import ArchiveRegistry
from app.archive.search import ArchiveSearch
from app.security import verify_owner_or_api_key

router = APIRouter(prefix="/archive", tags=["institutional-archive"])


class ImportRequest(BaseModel):
    source_path: str = Field(min_length=1)
    checkpoint_interval: int = Field(default=100, ge=1, le=10000)
    extract_zip: bool = True


class ResumeRequest(BaseModel):
    run_id: UUID


def _start_import(payload: ImportRequest) -> None:
    ArchiveImporter().start(Path(payload.source_path), ImportOptions(payload.checkpoint_interval, payload.extract_zip))


def _resume_import(run_id: UUID) -> None:
    ArchiveImporter().resume(run_id)


@router.post("/import", status_code=202, dependencies=[Depends(verify_owner_or_api_key)])
def import_archive(payload: ImportRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_start_import, payload)
    return {"accepted": True, "source_path": payload.source_path, "checkpoint_interval": payload.checkpoint_interval}


@router.post("/resume", status_code=202, dependencies=[Depends(verify_owner_or_api_key)])
def resume_archive(payload: ResumeRequest, background_tasks: BackgroundTasks):
    registry = ArchiveRegistry()
    if not registry.run(payload.run_id):
        raise HTTPException(status_code=404, detail="archive import run not found")
    background_tasks.add_task(_resume_import, payload.run_id)
    return {"accepted": True, "run_id": str(payload.run_id)}


@router.get("/status")
def archive_status(run_id: UUID | None = None):
    registry = ArchiveRegistry()
    run = registry.run(run_id) if run_id else registry.latest_run()
    return {"run": run, "checkpoint": None if not run else __import__("app.archive.checkpoint", fromlist=["CheckpointStore"]).CheckpointStore(registry).load(run["id"])}


@router.get("/statistics")
def archive_statistics():
    return ArchiveRegistry().statistics()


@router.get("/documents")
def archive_documents(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return {"items": ArchiveSearch().documents(limit=limit, offset=offset)}


@router.get("/entities")
def archive_entities(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return {"items": ArchiveSearch().entities(limit=limit, offset=offset)}
