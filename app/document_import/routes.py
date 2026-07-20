from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key
from .dependencies import get_bulk_import_service, get_import_repository, get_import_service

router = APIRouter(prefix="/api/brain/imports", tags=["drive-document-import"],
    dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)])


class SingleImport(BaseModel):
    registry_id: int = Field(gt=0)
    mission_id: int | None = Field(default=None, gt=0)


class BatchImport(BaseModel):
    registry_ids: list[int] = Field(min_length=1, max_length=25)
    mission_id: int | None = Field(default=None, gt=0)


class BulkPreview(BaseModel):
    source_id: str = Field(min_length=1)


def _actor(auth: dict[str, Any]) -> str:
    return str(auth.get("actor") or auth.get("subject") or auth.get("auth_type") or "owner_session")


def _translate(exc: Exception) -> HTTPException:
    code = str(exc)
    if isinstance(exc, LookupError): return HTTPException(404, detail={"code": code})
    if isinstance(exc, PermissionError): return HTTPException(403, detail={"code": code})
    if code == "UNSUPPORTED_FORMAT": return HTTPException(415, detail={"code": code})
    return HTTPException(409, detail={"code": code})


@router.post("/preview")
def preview(payload: SingleImport, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_import_service)]):
    try: return service.preview(payload.registry_id, _actor(auth))
    except Exception as exc: raise _translate(exc) from exc


@router.post("", status_code=201)
def import_single(payload: SingleImport, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_import_service)]):
    try: return service.import_one(payload.registry_id, _actor(auth), mission_id=payload.mission_id).as_dict()
    except Exception as exc: raise _translate(exc) from exc


@router.post("/batch", status_code=201)
def import_batch(payload: BatchImport, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_import_service)]):
    try: return service.import_batch(payload.registry_ids, _actor(auth), mission_id=payload.mission_id)
    except Exception as exc: raise _translate(exc) from exc


@router.get("/history")
def history(repository: Annotated[Any, Depends(get_import_repository)], registry_id: int | None = Query(default=None, gt=0), limit: int = Query(100, ge=1, le=500)):
    return {"items": repository.history(registry_id, limit)}


@router.post("/{session_id}/retry/{registry_id}")
def retry(session_id: int, registry_id: int, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_import_service)]):
    try: return service.retry(session_id, registry_id, _actor(auth)).as_dict()
    except Exception as exc: raise _translate(exc) from exc


@router.post("/{session_id}/cancel")
def cancel(session_id: int, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_import_service)]):
    try: return service.cancel(session_id, _actor(auth))
    except Exception as exc: raise _translate(exc) from exc


@router.post("/bulk/preview", status_code=201)
def preview_bulk(payload: BulkPreview, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_bulk_import_service)]):
    try: return service.preview(payload.source_id, _actor(auth))
    except Exception as exc: raise _translate(exc) from exc


@router.post("/bulk/{run_id}/execute")
def execute_bulk(run_id: int, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_bulk_import_service)]):
    try: return service.execute(run_id, _actor(auth))
    except Exception as exc: raise _translate(exc) from exc


@router.post("/bulk/{run_id}/resume")
def resume_bulk(run_id: int, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_bulk_import_service)]):
    try: return service.resume(run_id, _actor(auth))
    except Exception as exc: raise _translate(exc) from exc


@router.post("/bulk/{run_id}/cancel")
def cancel_bulk(run_id: int, auth: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)], service: Annotated[Any, Depends(get_bulk_import_service)]):
    try: return service.cancel(run_id, _actor(auth))
    except Exception as exc: raise _translate(exc) from exc


@router.get("/bulk/history")
def bulk_history(service: Annotated[Any, Depends(get_bulk_import_service)], limit: int = Query(100, ge=1, le=500)):
    return {"items":service.history(limit)}
