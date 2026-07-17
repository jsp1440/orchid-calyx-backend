from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key
from .repository import create_action, list_actions, source_workflow, update_action
from .schemas import ActionUpdateRequest, RouteActionRequest

router = APIRouter(
    prefix="/api/workflow",
    tags=["workflow-routing"],
    dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)],
)


@router.post("/sources/{source_id}/actions", status_code=201)
def route_source(source_id: int, payload: RouteActionRequest):
    result = create_action(source_id, payload)
    if not result:
        raise HTTPException(status_code=409, detail="Source must exist and be APPROVED before routing")
    return result


@router.get("/actions")
def actions(
    source_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    return {"items": list_actions(source_id=source_id, status=status, limit=limit)}


@router.patch("/actions/{action_id}")
def change_action(action_id: int, payload: ActionUpdateRequest):
    result = update_action(action_id, payload.status, payload.notes, payload.actor)
    if not result:
        raise HTTPException(status_code=404, detail="Workflow action not found")
    return result


@router.get("/sources/{source_id}")
def workflow_for_source(source_id: int):
    result = source_workflow(source_id)
    if not result:
        raise HTTPException(status_code=404, detail="Intake source not found")
    return result
