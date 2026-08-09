"""Protected Mission Control routes for BUILD-FIG-301 assisted figures."""
from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.figure_assisted_gateway import (
    AssistedFigureGateway,
    FigureBrief,
    FigureSource,
    orchid_root_velamen_brief,
)

router = APIRouter(
    prefix="/brain/mission-control/figures",
    tags=["mission-control-figures"],
    dependencies=[Depends(verify_owner_or_api_key)],
)
_service = AssistedFigureGateway()
_service.register_brief(orchid_root_velamen_brief())


class FigureSourceRequest(BaseModel):
    source_uri: str = Field(min_length=3, max_length=2000)
    citation: str = Field(min_length=1, max_length=2000)
    license: str = Field(min_length=2, max_length=100)
    evidence_sha256: str = Field(min_length=64, max_length=64)


class FigureBriefRequest(BaseModel):
    brief_id: str = Field(min_length=3, max_length=200)
    project_id: str = Field(min_length=3, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=4000)
    required_labels: list[str] = Field(min_length=1, max_length=100)
    source_records: list[FigureSourceRequest] = Field(min_length=1, max_length=100)
    output_formats: list[str] = Field(min_length=1, max_length=3)
    provider_hint: str | None = Field(default=None, max_length=200)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0, le=25.0)


class FigureImportRequest(BaseModel):
    format: str = Field(min_length=3, max_length=4)
    content_base64: str = Field(min_length=4, max_length=35_000_000)
    source_uri: str = Field(min_length=3, max_length=2000)
    creator: str = Field(min_length=1, max_length=500)
    attribution: str = Field(min_length=1, max_length=2000)
    license: str = Field(min_length=2, max_length=100)
    semantic_hotspots: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


@router.get("/fixtures/orchid-root-velamen")
def orchid_root_velamen_fixture() -> dict[str, Any]:
    return _service.brief_package("figure-brief:orchid-root-velamen-v1")


@router.post("/briefs")
def create_figure_brief(
    request: Annotated[FigureBriefRequest, Body()],
) -> dict[str, Any]:
    try:
        brief = FigureBrief(
            brief_id=request.brief_id,
            project_id=request.project_id,
            title=request.title,
            purpose=request.purpose,
            required_labels=tuple(request.required_labels),
            source_records=tuple(FigureSource(**item.model_dump()) for item in request.source_records),
            output_formats=tuple(request.output_formats),
            provider_hint=request.provider_hint,
            estimated_cost_usd=request.estimated_cost_usd,
        )
        return _service.register_brief(brief)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/briefs/{brief_id}")
def figure_brief(brief_id: str) -> dict[str, Any]:
    try:
        return _service.brief_package(brief_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/briefs/{brief_id}/imports")
def import_figure_asset(
    brief_id: str,
    request: Annotated[FigureImportRequest, Body()],
) -> dict[str, Any]:
    try:
        try:
            content = base64.b64decode(request.content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("ASSET_BASE64_INVALID") from exc
        asset = _service.import_asset(
            brief_id=brief_id,
            format=request.format,
            content=content,
            source_uri=request.source_uri,
            creator=request.creator,
            attribution=request.attribution,
            license=request.license,
            semantic_hotspots=request.semantic_hotspots,
        )
        return asdict(asset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/briefs/{brief_id}/readiness")
def figure_readiness(brief_id: str) -> dict[str, Any]:
    try:
        return _service.readiness(brief_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
