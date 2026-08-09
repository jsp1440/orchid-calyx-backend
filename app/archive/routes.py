from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.archive.activation import ArchiveActivationInspector
from app.archive.checkpoint import CheckpointStore
from app.archive.control import ArchiveRunControl
from app.archive.execution import get_archive_dispatcher
from app.archive.importer import ArchiveImporter, ImportOptions
from app.archive.policy import ArchivePolicy, ArchivePolicyError
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


def _dispatch_run(run_id: UUID) -> str:
    return get_archive_dispatcher().submit(lambda: ArchiveImporter().execute(run_id))


@router.post("/import", status_code=202, dependencies=[Depends(verify_owner_or_api_key)])
def import_archive(payload: ImportRequest):
    try:
        source = ArchivePolicy.from_environment().authorize_source(Path(payload.source_path))
    except ArchivePolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    options = ImportOptions(payload.checkpoint_interval, payload.extract_zip)
    control = ArchiveRunControl()
    run_id = control.create_queued_run(str(source), asdict(options))
    reference = _dispatch_run(run_id)
    control.set_dispatch_reference(run_id, reference)
    return {
        "accepted": True,
        "run_id": str(run_id),
        "dispatch_reference": reference,
        "source_path": str(source),
        "checkpoint_interval": payload.checkpoint_interval,
    }


@router.post("/resume", status_code=202, dependencies=[Depends(verify_owner_or_api_key)])
def resume_archive(payload: ResumeRequest):
    registry = ArchiveRegistry()
    run = registry.run(payload.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="archive import run not found")
    if run["status"] not in {"interrupted", "failed"}:
        raise HTTPException(status_code=409, detail="archive import run is not resumable")
    reference = _dispatch_run(payload.run_id)
    ArchiveRunControl(registry).set_dispatch_reference(payload.run_id, reference)
    return {
        "accepted": True,
        "run_id": str(payload.run_id),
        "dispatch_reference": reference,
    }


@router.post("/cancel/{run_id}", dependencies=[Depends(verify_owner_or_api_key)])
def cancel_archive(run_id: UUID):
    control = ArchiveRunControl()
    if not control.request_cancel(run_id):
        raise HTTPException(status_code=409, detail="archive import run cannot be cancelled")
    return {"accepted": True, "run_id": str(run_id), "status": "cancelling"}


@router.post("/recover-stale", dependencies=[Depends(verify_owner_or_api_key)])
def recover_stale_archive_runs():
    return {"recovered": ArchiveRunControl().recover_stale_runs()}


@router.get("/activation/status", dependencies=[Depends(verify_owner_or_api_key)])
def archive_activation_status():
    return asdict(ArchiveActivationInspector().inspect())


@router.get("/activation/contracts", dependencies=[Depends(verify_owner_or_api_key)])
def archive_activation_contracts():
    return ArchiveActivationInspector().contract_inventory()


@router.post("/activation/evidence", dependencies=[Depends(verify_owner_or_api_key)])
def archive_activation_evidence():
    return ArchiveActivationInspector().sanitized_evidence()


@router.get("/status")
def archive_status(run_id: UUID | None = None):
    registry = ArchiveRegistry()
    run = registry.run(run_id) if run_id else registry.latest_run()
    checkpoint = None if not run else CheckpointStore(registry).load(run["id"])
    return {"run": run, "checkpoint": checkpoint}


@router.get("/statistics")
def archive_statistics():
    return ArchiveRegistry().statistics()


@router.get("/runs")
def archive_runs(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return {"items": ArchiveSearch().runs(status=status, limit=limit, offset=offset)}


@router.get("/manifest/{run_id}")
def archive_manifest(run_id: UUID):
    try:
        return ArchiveRegistry().manifest(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="archive import run not found") from exc


@router.get("/documents")
def archive_documents(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return {"items": ArchiveSearch().documents(query=q, limit=limit, offset=offset)}


@router.get("/documents/{document_id}")
def archive_document(document_id: UUID):
    result = ArchiveSearch().document(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="archive document not found")
    return result


@router.get("/entities")
def archive_entities(
    q: str | None = Query(default=None, max_length=200),
    entity_type: str | None = Query(default=None, max_length=100),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return {
        "items": ArchiveSearch().entities(
            query=q,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
        )
    }
