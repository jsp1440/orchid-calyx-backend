from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from app.design_planning.routes import PLANNING_REPOSITORY
from app.persistence.state_repository import configured_database_url
from app.security import verify_owner_or_api_key

from .repository import MemoryImplementationPlanningRepository
from .service import (
    ImplementationPlanningError,
    ImplementationSpecificationService,
    SourcePlanningBundle,
)

router = APIRouter(
    prefix="/api/implementation-planning",
    tags=["implementation-planning"],
    dependencies=[Depends(verify_owner_or_api_key)],
)
if database_url := configured_database_url():
    from .postgres_repository import PostgresImplementationPlanningRepository

    REPOSITORY = PostgresImplementationPlanningRepository(database_url)
else:
    REPOSITORY = MemoryImplementationPlanningRepository()
SERVICE = ImplementationSpecificationService(REPOSITORY)


def actor(x_calyx_actor: str = Header(..., min_length=1, max_length=200)):
    return x_calyx_actor


def roles(x_calyx_roles: str = Header("")):
    return {x.strip() for x in x_calyx_roles.split(",") if x.strip()}


def call(method, *args):
    try:
        return asdict(method(*args))
    except ImplementationPlanningError as exc:
        raise HTTPException(
            404 if str(exc).endswith("NOT_FOUND") else 422, detail={"code": str(exc)}
        ) from exc


def source_bundle(plan_id: str):
    plan = PLANNING_REPOSITORY.get("plan", plan_id)
    if plan is None:
        raise ImplementationPlanningError("SOURCE_PLAN_NOT_FOUND")
    request = PLANNING_REPOSITORY.get("product_request", plan.product_request_id)
    context = PLANNING_REPOSITORY.get("context", plan.context_snapshot_id)
    evidence = PLANNING_REPOSITORY.get("evidence", plan.evidence_package_ids[0])
    reasoning = tuple(
        PLANNING_REPOSITORY.get("reasoning", x) for x in plan.reasoning_record_ids
    )
    conflicts = tuple(
        PLANNING_REPOSITORY.get("conflict", x) for x in plan.conflict_record_ids
    )
    if not all((request, context, evidence, *reasoning, *conflicts)):
        raise ImplementationPlanningError("INCOMPLETE_SOURCE_ARTIFACT_CHAIN")
    return SourcePlanningBundle(request, context, evidence, reasoning, conflicts, plan)


@router.post("/specifications/my-conservatory/generate", status_code=201)
def generate(payload: dict = Body(...), identity: str = Depends(actor)):  # noqa: B008
    if set(payload) != {"source_plan_id"}:
        raise HTTPException(422, detail={"code": "ONLY_SOURCE_PLAN_ID_ACCEPTED"})
    return call(
        SERVICE.generate_my_conservatory,
        source_bundle(payload["source_plan_id"]),
        identity,
    )


def spec(specification_id):
    return SERVICE.get(specification_id)


@router.get("/specifications/{specification_id}")
def get_spec(specification_id: str):
    return call(SERVICE.get, specification_id)


@router.get("/specifications/{specification_id}/pages")
def pages(specification_id: str):
    return [asdict(x) for x in spec(specification_id).pages]


@router.get("/specifications/{specification_id}/components")
def components(specification_id: str):
    return [asdict(x) for x in spec(specification_id).components]


@router.get("/specifications/{specification_id}/navigation")
def navigation(specification_id: str):
    return asdict(spec(specification_id).navigation)


@router.get("/specifications/{specification_id}/state")
def state(specification_id: str):
    return [asdict(x) for x in spec(specification_id).states]


@router.get("/specifications/{specification_id}/api-contracts")
def apis(specification_id: str):
    return [asdict(x) for x in spec(specification_id).api_contracts]


@router.get("/specifications/{specification_id}/data-contracts")
def data(specification_id: str):
    return [asdict(x) for x in spec(specification_id).data_contracts]


@router.get("/specifications/{specification_id}/readiness")
def readiness(specification_id: str):
    return [asdict(x) for x in spec(specification_id).readiness]


@router.get("/specifications/{specification_id}/sequence")
def sequence(specification_id: str):
    return [asdict(x) for x in spec(specification_id).sequence]


@router.get("/specifications/{specification_id}/history")
def history(specification_id: str):
    return [asdict(x) for x in REPOSITORY.history(spec(specification_id).logical_key)]


@router.post("/specifications/{specification_id}/reviews", status_code=201)
def review(
    specification_id: str,
    payload: dict = Body(...),  # noqa: B008
    identity: str = Depends(actor),
    reviewer_roles: set[str] = Depends(roles),  # noqa: B008
):
    return call(SERVICE.review, specification_id, payload, identity, reviewer_roles)


@router.get("/audit")
def audit(specification_id: str | None = None):
    return [
        x if isinstance(x, dict) else asdict(x)
        for x in REPOSITORY.audits(specification_id)
    ]


@router.get("/health")
def health():
    return SERVICE.health()
