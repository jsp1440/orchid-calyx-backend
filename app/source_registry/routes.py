from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key
from .dependencies import get_scan_service, get_source_repository

router = APIRouter(prefix="/api/brain/sources", tags=["brain-source-registry"], dependencies=[Depends(verify_owner_or_api_key),Depends(add_mission_control_cors_headers)])


class GoogleDriveRegistration(BaseModel):
    source_name: str = Field(min_length=1, max_length=200)
    authentication_method: str = Field(default="SERVICE_ACCOUNT", pattern="^(SERVICE_ACCOUNT|APPLICATION_DEFAULT_CREDENTIALS)$")
    folder_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/google-drive", status_code=201)
def register_google_drive(payload: GoogleDriveRegistration, repository: Annotated[Any, Depends(get_source_repository)]):
    return repository.register_google_drive(payload.source_name, payload.authentication_method, payload.folder_ids)


@router.get("")
def sources(repository: Annotated[Any, Depends(get_source_repository)]):
    return {"items": repository.list_sources()}


@router.post("/{source_id}/scan")
def scan(source_id: str, repository: Annotated[Any, Depends(get_source_repository)], service: Annotated[Any, Depends(get_scan_service)]):
    source = repository.get_source(source_id)
    if not source:
        raise HTTPException(404, detail={"code":"SOURCE_NOT_FOUND"})
    if source["source_type"] != "GOOGLE_DRIVE":
        raise HTTPException(409, detail={"code":"UNSUPPORTED_SOURCE_TYPE"})
    result = service.scan(source_id, list(source["configuration"].get("folder_ids", [])))
    return {**result.__dict__, "metadata_only": True, "graph_mutated": False}


@router.get("/{source_id}/scans")
def scans(source_id: str, repository: Annotated[Any, Depends(get_source_repository)], limit: int = Query(50, ge=1, le=200)):
    return {"items": repository.scan_logs(source_id, limit)}


@router.get("/dashboard/summary")
def dashboard(repository: Annotated[Any, Depends(get_source_repository)]):
    return repository.dashboard()

