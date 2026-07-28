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
    EvidencePacketStore,
    EvidencePreviewService,
    MarkdownExportService,
)

router = APIRouter(
    prefix="/api/calyx-journalism",
    tags=["CALYX-JOURNALISM-MVP-001"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

# Shared in-process stores — same-day MVP; no database required
_store = ArticleStore()
_packet_store = EvidencePacketStore()
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
    packet = _preview_service.build_preview(
        evidence_items=payload.evidence_items,
        available_dependencies=payload.available_dependencies or None,
    )
    _packet_store.save(packet)
    return packet


# ---------------------------------------------------------------------------
# Article generation
# ---------------------------------------------------------------------------

@router.post("/generate", status_code=201)
def generate_article(request: ArticleGenerationRequest) -> ArticleGenerationResponse:
    # Resolve evidence: packet store lookup takes precedence over inline items
    evidence_items: list[dict[str, Any]] = list(request.evidence_items)
    verified_projects_override = None

    if request.evidence_packet_id:
        packet = _packet_store.get(request.evidence_packet_id)
        if packet is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "EVIDENCE_PACKET_NOT_FOUND",
                    "evidence_packet_id": request.evidence_packet_id,
                },
            )
        evidence_items = list(packet.items)
        verified_projects_override = list(packet.verified_projects)

    response = _generation_service.generate(
        request,
        evidence_items=evidence_items,
        verified_projects_override=verified_projects_override,
    )
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
