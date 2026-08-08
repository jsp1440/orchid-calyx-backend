"""Protected Mission Control routes for CALYX homepage governance."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.homepage_governance import HomepageGovernanceService

router = APIRouter(prefix="/brain/mission-control/homepage", tags=["mission-control-homepage"])
_service_instance = HomepageGovernanceService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> HomepageGovernanceService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "HOMEPAGE_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "HOMEPAGE_RECORD_NOT_FOUND", "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class AuditRequest(BaseModel):
    audit_id: str
    deployed_revision: str
    source_screenshots: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    route_inventory: list[str] = Field(default_factory=list, max_length=500)
    findings: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    evidence_anchors: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    provenance: list[dict[str, Any] | str] = Field(min_length=1, max_length=5000)


class SpecificationRequest(BaseModel):
    specification_id: str
    audit_id: str
    audit_version: int = Field(ge=1)
    required_sections: list[str] = Field(min_length=1, max_length=500)
    required_routes: list[str] = Field(default_factory=list, max_length=500)
    required_components: list[str] = Field(default_factory=list, max_length=1000)
    scientific_wording_rules: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    accessibility_requirements: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    visual_requirements: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    taxonomy_requirements: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    media_requirements: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    evidence_requirements: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    evidence_anchors: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    implementation_brief: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any] | str] = Field(min_length=1, max_length=5000)


class ApprovalRequest(BaseModel):
    rationale: str = Field(min_length=1, max_length=4000)


class ImplementationRequest(BaseModel):
    implementation_id: str
    specification_id: str
    specification_version: int = Field(ge=1)
    implementation_revision: str
    manifest: dict[str, Any]
    implementation_screenshots: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    returned_artifact_metadata: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    implementation_provider: str | None = None


class ValidationRequest(BaseModel):
    checks: dict[str, dict[str, Any]]


@router.post("/audits")
def submit_audit(request: AuditRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().submit_audit(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/audits/{audit_id}")
def get_audit(audit_id: str, identity: Identity, version: Annotated[int | None, Query(ge=1)] = None) -> dict[str, Any]:
    try:
        return _service().get_audit(_owner(identity), audit_id, version)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/specifications")
def submit_specification(request: SpecificationRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().submit_specification(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/specifications/{specification_id}")
def get_specification(specification_id: str, identity: Identity, version: Annotated[int | None, Query(ge=1)] = None) -> dict[str, Any]:
    try:
        return _service().get_specification(_owner(identity), specification_id, version)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/specifications/{specification_id}/versions/{version}/approve")
def approve_specification(specification_id: str, version: int, request: ApprovalRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().approve_specification(owner, specification_id, version, actor=owner, rationale=request.rationale)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/implementations")
def receive_implementation(request: ImplementationRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().receive_implementation(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/implementations/{implementation_id}/validate")
def validate_implementation(implementation_id: str, request: ValidationRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().validate(_owner(identity), implementation_id, request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/implementations/{implementation_id}/readiness")
def implementation_readiness(implementation_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().readiness(_owner(identity), implementation_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc
