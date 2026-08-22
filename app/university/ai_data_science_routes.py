from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .ai_data_science import AppliedAIDataScienceService, MODULE_ID
from .config import session_writes_enabled, university_enabled
from .learner_auth import verify_university_actor

router = APIRouter(
    prefix="/ai-data-science",
    tags=["orchid-continuum-university-ai-data-science"],
)
UniversityActor = Annotated[dict, Depends(verify_university_actor)]
_service_instance = AppliedAIDataScienceService()


class PrepareModuleRequest(BaseModel):
    rows: list[dict[str, Any]]
    provenance: dict[str, Any]
    selection: dict[str, Any] = Field(default_factory=dict)
    question: str | None = None
    rationale: str | None = None
    recorded_at: str
    project_id: str | None = None


class ExecuteModuleRequest(BaseModel):
    recorded_at: str


def _require_university() -> None:
    if not university_enabled():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "UNIVERSITY_DISABLED",
                "message": "Orchid Continuum University is disabled",
            },
        )


def _require_session_writes() -> None:
    _require_university()
    if not session_writes_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "UNIVERSITY_SESSION_WRITES_DISABLED",
                "message": "University learning/research writes are disabled",
            },
        )


def _owner(auth: dict) -> str:
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"},
        )
    return actor


def _translate(operation):
    try:
        return operation()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "OC_AI_DS_RESOURCE_NOT_FOUND", "resource": str(exc)},
        ) from exc
    except (TypeError, ValueError, LookupError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "OC_AI_DS_VALIDATION_ERROR", "message": str(exc)},
        ) from exc


@router.get("/modules/{module_id}")
def get_module(module_id: str) -> dict[str, Any]:
    _require_university()
    if module_id != MODULE_ID:
        raise HTTPException(
            status_code=404,
            detail={"code": "OC_AI_DS_MODULE_NOT_FOUND"},
        )
    return _service_instance.module()


@router.post("/modules/{module_id}/prepare")
def prepare_module(
    module_id: str,
    request: PrepareModuleRequest,
    auth: UniversityActor,
) -> dict[str, Any]:
    _require_session_writes()
    if module_id != MODULE_ID:
        raise HTTPException(
            status_code=404,
            detail={"code": "OC_AI_DS_MODULE_NOT_FOUND"},
        )
    payload = request.model_dump()
    return _translate(lambda: _service_instance.prepare(_owner(auth), payload))


@router.get("/projects/{project_id}/manifests/{manifest_id}")
def get_manifest(
    project_id: str,
    manifest_id: str,
    auth: UniversityActor,
) -> dict[str, Any]:
    _require_session_writes()
    return _translate(
        lambda: _service_instance.get_manifest(_owner(auth), project_id, manifest_id)
    )


@router.post("/projects/{project_id}/manifests/{manifest_id}/execute")
def execute_manifest(
    project_id: str,
    manifest_id: str,
    request: ExecuteModuleRequest,
    auth: UniversityActor,
) -> dict[str, Any]:
    _require_session_writes()
    return _translate(
        lambda: _service_instance.execute(
            _owner(auth), project_id, manifest_id, request.recorded_at
        )
    )
