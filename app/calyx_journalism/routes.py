"""FastAPI routes for durable Calyx journalism workflows."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .persistence import SqlAlchemyJournalismRepository
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
    EvidencePreviewService,
    MarkdownExportService,
)

router = APIRouter(
    prefix="/journalism",
    tags=["CALYX-JOURNALISM-003"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

_preview_service = EvidencePreviewService()
_generation_service = ArticleGenerationService()
_export_service = MarkdownExportService()

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


def _actor(auth: dict[str, Any]) -> str:
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_ACTOR_REQUIRED"})
    return actor


def _repository(db: Session) -> SqlAlchemyJournalismRepository:
    return SqlAlchemyJournalismRepository(db)


@router.get("/presets")
def get_presets() -> dict[str, Any]:
    presets = list_presets()
    return {"count": len(presets), "presets": presets}


@router.get("/presets/{preset_id}")
def get_preset_by_id(preset_id: str) -> dict[str, Any]:
    preset = get_preset(preset_id)
    if preset is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PRESET_NOT_FOUND", "preset_id": preset_id},
        )
    return preset


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


class EvidencePreviewRequest(BaseModel):
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    available_dependencies: list[str] = Field(default_factory=list)


@router.post("/evidence-preview", status_code=201)
def evidence_preview(
    payload: EvidencePreviewRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> EvidencePreviewPacket:
    actor = _actor(auth)
    packet = _preview_service.build_preview(
        evidence_items=payload.evidence_items,
        available_dependencies=payload.available_dependencies or None,
    )
    return _repository(db).save_packet(
        packet,
        owner=actor,
        actor=actor,
        request_metadata={"available_dependencies": payload.available_dependencies},
    )


@router.get("/evidence-packets/{packet_id}")
def get_evidence_packet(
    packet_id: str,
    auth: AuthDependency,
    db: DbDependency,
) -> EvidencePreviewPacket:
    packet = _repository(db).get_packet(packet_id, owner=_actor(auth))
    if packet is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "EVIDENCE_PACKET_NOT_FOUND", "evidence_packet_id": packet_id},
        )
    return packet


@router.post("/generate", status_code=201)
def generate_article(
    request: ArticleGenerationRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> ArticleGenerationResponse:
    actor = _actor(auth)
    repository = _repository(db)
    evidence_items: list[dict[str, Any]] = list(request.evidence_items)
    verified_projects_override = None

    if request.evidence_packet_id:
        packet = repository.get_packet(request.evidence_packet_id, owner=actor)
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
    return repository.save_article(
        response,
        owner=actor,
        actor=actor,
        evidence_packet_id=request.evidence_packet_id,
        request_metadata={
            "publication_id": request.publication.publication_id,
            "brief_title": request.brief.title,
        },
    )


@router.get("/articles/{article_id}")
def get_article(
    article_id: str,
    auth: AuthDependency,
    db: DbDependency,
) -> ArticleGenerationResponse:
    article = _repository(db).get_article(article_id, owner=_actor(auth))
    if article is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTICLE_NOT_FOUND", "article_id": article_id},
        )
    return article


class MarkdownExportIn(BaseModel):
    article_id: str = Field(min_length=1)
    publication: PublicationMeta
    brief: ArticleBrief


@router.post("/export/markdown")
def export_markdown(
    payload: MarkdownExportIn,
    auth: AuthDependency,
    db: DbDependency,
) -> MarkdownExportResponse:
    article = _repository(db).get_article(payload.article_id, owner=_actor(auth))
    if article is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTICLE_NOT_FOUND", "article_id": payload.article_id},
        )
    return _export_service.export(article, payload.publication, payload.brief)
