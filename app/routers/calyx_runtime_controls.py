"""Authenticated Mission Control API for governed Calyx runtime controls."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from runtime.runtime_operator_controls import RuntimeOperatorControls


class OwnerApprovalRequest(BaseModel):
    owner_approved: bool


class RuntimeConfigurationRequest(OwnerApprovalRequest):
    interval_minutes: int = Field(ge=15, le=1440)
    max_draft_prs_per_cycle: int = Field(default=1, ge=0, le=5)


def create_runtime_controls_router(
    get_controls: Callable[[], RuntimeOperatorControls],
    require_owner: Callable[[], Any],
) -> APIRouter:
    router = APIRouter(
        prefix="/brain/mission-control/runtime",
        tags=["mission-control-runtime"],
    )

    @router.get("/status")
    def status() -> dict[str, Any]:
        return get_controls().status()

    @router.post("/pause", dependencies=[Depends(require_owner)])
    def pause(request: OwnerApprovalRequest) -> dict[str, Any]:
        return get_controls().pause(owner_approved=request.owner_approved)

    @router.post("/resume", dependencies=[Depends(require_owner)])
    def resume(request: OwnerApprovalRequest) -> dict[str, Any]:
        return get_controls().resume(owner_approved=request.owner_approved)

    @router.post("/run-once", dependencies=[Depends(require_owner)])
    def run_once(request: OwnerApprovalRequest) -> dict[str, Any]:
        return get_controls().run_once(owner_approved=request.owner_approved)

    @router.post("/configure", dependencies=[Depends(require_owner)])
    def configure(request: RuntimeConfigurationRequest) -> dict[str, Any]:
        return get_controls().configure(
            owner_approved=request.owner_approved,
            interval_minutes=request.interval_minutes,
            max_draft_prs_per_cycle=request.max_draft_prs_per_cycle,
        )

    return router
