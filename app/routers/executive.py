"""BUILD-052 read-only Calyx Executive Intelligence API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from runtime.executive.engine import build_executive_state

router = APIRouter(prefix="/api/executive", tags=["BUILD-052 Executive Intelligence"])


def state() -> dict[str, Any]:
    return build_executive_state()


@router.get("/state")
def executive_state() -> dict[str, Any]:
    return state()


@router.get("/summary")
def executive_summary() -> dict[str, Any]:
    current = state()
    return {"build": current["build"], "generated_at": current["generated_at"], **current["summary"]}


@router.get("/priorities")
def executive_priorities() -> dict[str, Any]:
    current = state()
    return {"build": current["build"], "generated_at": current["generated_at"], "priorities": current["priorities"]}


@router.get("/recommendations")
def executive_recommendations() -> dict[str, Any]:
    current = state()
    return {"build": current["build"], "generated_at": current["generated_at"], "recommendations": current["recommendations"]}


@router.get("/changes")
def executive_changes() -> dict[str, Any]:
    current = state()
    return {"build": current["build"], "generated_at": current["generated_at"], "changes": current["changes"]}


@router.get("/dependencies")
def executive_dependencies() -> dict[str, Any]:
    current = state()
    return {"build": current["build"], "generated_at": current["generated_at"], **current["dependencies"]}


@router.get("/briefing")
def executive_briefing() -> dict[str, Any]:
    current = state()
    return {"build": current["build"], **current["briefing"]}

