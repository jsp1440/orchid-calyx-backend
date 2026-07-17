from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key
from .repository import (
    budget_summary,
    decide,
    generate_for_source,
    list_providers,
    list_recommendations,
    record_usage,
    route_provider,
    route_recommendation,
    upsert_budget_policy,
    upsert_provider,
)
from .schemas import (
    BudgetPolicyUpsertRequest,
    ProviderRouteRequest,
    ProviderUpsertRequest,
    RecommendationDecisionRequest,
    RecommendationGenerateRequest,
    RecommendationRouteRequest,
    UsageRecordRequest,
)

router = APIRouter(
    prefix="/api/executive-intelligence",
    tags=["executive-intelligence"],
    dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)],
)


@router.post("/sources/{source_id}/recommendations")
def generate(source_id: int, payload: RecommendationGenerateRequest):
    items = generate_for_source(source_id, payload.workspace_id, payload.project_id)
    if items is None:
        raise HTTPException(status_code=409, detail="Source must exist and be APPROVED before recommendation generation")
    return {"source_id": source_id, "items": items, "canonical_records_mutated": False}


@router.get("/recommendations")
def recommendations(status: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500)):
    return {"items": list_recommendations(status=status, limit=limit)}


@router.patch("/recommendations/{recommendation_id}")
def recommendation_decision(recommendation_id: int, payload: RecommendationDecisionRequest):
    result = decide(recommendation_id, payload.decision, payload.actor, payload.notes)
    if not result:
        raise HTTPException(status_code=404, detail="Pending recommendation not found")
    return result


@router.post("/recommendations/{recommendation_id}/route", status_code=201)
def recommendation_route(recommendation_id: int, payload: RecommendationRouteRequest):
    result = route_recommendation(recommendation_id, payload)
    if not result:
        raise HTTPException(status_code=409, detail="Recommendation must exist and be APPROVED before routing")
    return result


@router.get("/providers")
def providers():
    return {"items": list_providers()}


@router.put("/providers/{provider_key}")
def provider_upsert(provider_key: str, payload: ProviderUpsertRequest):
    if provider_key != payload.provider_key:
        raise HTTPException(status_code=422, detail="provider_key path and body must match")
    return upsert_provider(payload)


@router.post("/providers/route")
def provider_route(payload: ProviderRouteRequest):
    result = route_provider(payload.capability, payload.workspace_id, payload.project_id,
        payload.estimated_cost_usd, payload.preferred_provider)
    if result["budget"]["decision"] == "BLOCK":
        raise HTTPException(status_code=402, detail=result)
    if not result["routing"]["selected"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@router.put("/budget-policies")
def budget_policy_upsert(payload: BudgetPolicyUpsertRequest):
    return upsert_budget_policy(payload)


@router.get("/budgets/summary")
def budgets(workspace_id: str = Query(default="default"), project_id: str | None = Query(default=None)):
    return budget_summary(workspace_id, project_id)


@router.post("/usage", status_code=201)
def usage(payload: UsageRecordRequest):
    return record_usage(payload)
