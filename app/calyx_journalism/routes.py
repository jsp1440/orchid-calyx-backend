"""FastAPI routes for the Calyx Journalism MVP.

MISSION-CONTROL-CALYX-JOURNALISM-MVP-001

Endpoints:
  GET  /api/calyx-journalism/presets              — list article presets
  GET  /api/calyx-journalism/presets/{preset_id}  — fetch a single preset
  POST /api/calyx-journalism/brief                — validate and echo a brief
  POST /api/calyx-journalism/evidence-preview     — build evidence preview packet
  POST /api/calyx-journalism/generate             — generate article (contract)
  POST /api/calyx-journalism/export/markdown      — export stored article to Markdown
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from fastapi import Depends

from .presets import get_preset, list_presets
from .schemas import (
    ArticleBrief,
    ArticleGenerationRequest,
    ArticleGenerationResponse,
    EvidencePreviewPacket,
    MarkdownExportResponse,
    PublicationMeta,
)
from .services import (
    ArticleGenerationService,
    ArticleStore,
    EvidencePreviewService,
    MarkdownExportService,
)

router = APIRouter(
    prefix="/api/calyx-journalism",
    tags=["CALYX-JOURNALISM-MVP-001"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

# Shared in-process store — same-day MVP; no database required
_store = ArticleStore()
_preview_service = EvidencePreviewService()
_generation_service = ArticleGenerationService()
_export_service = MarkdownExportService()


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

@router.get("/presets")
def get_presets() -> dict[str, Any]:
    presets = list_presets()
    return {"count": len(presets), "presets": presets}


@router.get("/presets/{preset_id}")
def get_preset_by_id(preset_id: str) -> dict[str, Any]:
    preset = get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail={"code": "PRESET_NOT_FOUND", "preset_id": preset_id})
    return preset


# ---------------------------------------------------------------------------
# Brief submission
# ---------------------------------------------------------------------------

class BriefSubmissionRequest(BaseModel):
    publication: PublicationMeta
    brief: ArticleBrief


@router.post("/brief", status_code=201)
def submit_brief(payload: BriefSubmissionRequest) -> dict[str, Any]:
    return {
        "accepted": True,
        "publication": payload.publication.model_dump(),
        "brief": payload.brief.model_dump(),
    }


# ---------------------------------------------------------------------------
# Evidence preview
# ---------------------------------------------------------------------------

class EvidencePreviewRequest(BaseModel):
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    available_dependencies: list[str] = Field(default_factory=list)


@router.post("/evidence-preview", status_code=201)
def evidence_preview(payload: EvidencePreviewRequest) -> EvidencePreviewPacket:
    return _preview_service.build_preview(
        evidence_items=payload.evidence_items,
        available_dependencies=payload.available_dependencies or None,
    )


# ---------------------------------------------------------------------------
# Article generation
# ---------------------------------------------------------------------------

@router.post("/generate", status_code=201)
def generate_article(request: ArticleGenerationRequest) -> ArticleGenerationResponse:
    response = _generation_service.generate(request)
    _store.save(response)
    return response


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

class MarkdownExportIn(BaseModel):
    article_id: str = Field(min_length=1)
    publication: PublicationMeta
    brief: ArticleBrief


@router.post("/export/markdown")
def export_markdown(payload: MarkdownExportIn) -> MarkdownExportResponse:
    article = _store.get(payload.article_id)
    if article is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTICLE_NOT_FOUND", "article_id": payload.article_id},
        )
    return _export_service.export(article, payload.publication, payload.brief)
