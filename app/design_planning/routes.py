from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from app.design_intelligence.routes import REASONING_SERVICE
from app.persistence.state_repository import configured_database_url
from app.security import verify_owner_or_api_key

from .models import LifecycleState
from .service import Build089EvidenceAdapter, DesignPlanningService, PlanningError


router = APIRouter(
    prefix="/api/design-planning",
    tags=["design-planning"],
    dependencies=[Depends(verify_owner_or_api_key)],
)
if database_url := configured_database_url():
    from .postgres_repository import PostgresDesignPlanningRepository

    PLANNING_REPOSITORY = PostgresDesignPlanningRepository(database_url)
else:
    from .repository import MemoryDesignPlanningRepository

    PLANNING_REPOSITORY = MemoryDesignPlanningRepository()
SERVICE = DesignPlanningService(
    repository=PLANNING_REPOSITORY,
    evidence_adapter=Build089EvidenceAdapter(REASONING_SERVICE),
)
FORBIDDEN_INPUTS = {
    "integrity_hash",
    "created_at",
    "lifecycle_state",
    "approval_status",
    "provenance",
    "audit_identity",
    "implementation_authorization",
    "corpus_evidence",
}


def actor(
    x_calyx_actor: Annotated[str, Header(min_length=1, max_length=200)],
) -> str:
    return x_calyx_actor


def roles(x_calyx_roles: Annotated[str, Header()] = "") -> set[str]:
    return {item.strip() for item in x_calyx_roles.split(",") if item.strip()}


def safe(payload: dict[str, Any]) -> dict[str, Any]:
    if FORBIDDEN_INPUTS.intersection(payload):
        raise HTTPException(422, detail={"code": "CALLER_CONTROLLED_TRUSTED_FIELD"})
    return payload


def call(method, *args):
    try:
        return asdict(method(*args))
    except PlanningError as exc:
        code = str(exc)
        status = (
            404 if code.endswith("_NOT_FOUND") else 409 if "CONFLICT" in code else 422
        )
        raise HTTPException(status, detail={"code": code}) from exc


@router.post("/product-requests", status_code=201)
def create_product_request(
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
):
    return call(SERVICE.create_product_request, safe(payload), identity)


@router.post("/product-requests/{request_id}/versions", status_code=201)
def create_product_request_version(
    request_id: str,
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
):
    prior = SERVICE.repository.get("product_request", request_id)
    if prior is None:
        raise HTTPException(404, detail={"code": "PRODUCT_REQUEST_NOT_FOUND"})
    payload = safe(payload)
    payload["logical_key"] = prior.logical_key
    return call(SERVICE.create_product_request, payload, identity)


@router.get("/product-requests/{request_id}")
def read_product_request(request_id: str):
    return call(SERVICE._get, "product_request", request_id)


@router.post("/product-requests/{request_id}/contexts", status_code=201)
def create_context(
    request_id: str,
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
):
    return call(SERVICE.create_context, request_id, safe(payload), identity)


@router.post("/product-requests/{request_id}/evidence-packages", status_code=201)
def build_evidence(
    request_id: str,
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
):
    context_id = payload.pop("context_snapshot_id", None)
    if not context_id:
        raise HTTPException(422, detail={"code": "MISSING_CONTEXT_SNAPSHOT_ID"})
    return call(SERVICE.build_evidence, request_id, context_id, safe(payload), identity)


@router.post("/reasoning-records", status_code=201)
def create_reasoning(
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
):
    return call(SERVICE.create_reasoning, safe(payload), identity)


@router.post("/conflicts", status_code=201)
def create_conflict(
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
):
    return call(SERVICE.create_conflict, safe(payload), identity)


@router.post("/interface-plans", status_code=201)
def create_plan(
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
):
    return call(SERVICE.create_plan, safe(payload), identity)


@router.post("/interface-plans/{plan_id}/submit")
def submit_plan(plan_id: str, identity: Annotated[str, Depends(actor)]):
    return call(
        SERVICE.transition_plan, plan_id, LifecycleState.REVIEW_REQUIRED, identity
    )


@router.post("/interface-plans/{plan_id}/reviews", status_code=201)
def review_plan(
    plan_id: str,
    payload: Annotated[dict[str, Any], Body()],
    identity: Annotated[str, Depends(actor)],
    reviewer_roles: Annotated[set[str], Depends(roles)],
):
    return call(SERVICE.review, plan_id, safe(payload), identity, reviewer_roles)


@router.get("/artifacts/{kind}/{logical_key}/history")
def artifact_history(kind: str, logical_key: str):
    if kind not in {
        "product_request",
        "context",
        "evidence",
        "reasoning",
        "conflict",
        "plan",
    }:
        raise HTTPException(422, detail={"code": "INVALID_ARTIFACT_KIND"})
    return [asdict(item) for item in SERVICE.repository.history(kind, logical_key)]


@router.get("/audit")
def audit_history(artifact_id: str | None = None):
    return [asdict(item) for item in SERVICE.repository.audits(artifact_id)]


@router.get("/health")
def planning_health():
    return SERVICE.health()
