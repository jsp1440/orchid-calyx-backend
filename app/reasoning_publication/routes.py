from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.reasoning_ledger.routes import _invoke, _subject
from app.security import verify_owner_or_api_key

from .eligibility import discover_eligible_ledgers
from .gateway import ExistingKnowledgeGraphPublicationGate
from .schemas import PublishLedgerIn
from .service import ReasoningLedgerPublicationService

router = APIRouter(
    prefix="/api/reasoning-ledgers", tags=["reasoning-ledger-publication"]
)
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]
Db = Annotated[Session, Depends(get_db)]


@router.get("/eligible-for-publication")
def eligible_for_publication(request: Request, auth: Auth, db: Db):
    owner = _subject(auth)
    return _invoke(db, request, lambda: discover_eligible_ledgers(db, owner))


@router.post("/{ledger_id}/publish")
def publish_ledger(
    ledger_id: str,
    payload: PublishLedgerIn,
    request: Request,
    auth: Auth,
    db: Db,
):
    owner = _subject(auth)
    artifact, created = _invoke(
        db,
        request,
        lambda: ReasoningLedgerPublicationService(
            db, ExistingKnowledgeGraphPublicationGate.from_environment()
        ).publish(
            ledger_id,
            owner=owner,
            expected_version=payload.expected_version,
            expected_review_content_hash=payload.expected_review_content_hash,
            note=payload.publication_note,
        ),
    )
    return {"created": created, "artifact": artifact, "automatic_publication": False}


@router.get("/{ledger_id}/publications")
def publication_history(
    ledger_id: str,
    request: Request,
    auth: Auth,
    db: Db,
):
    owner = _subject(auth)
    return {
        "items": _invoke(
            db,
            request,
            lambda: ReasoningLedgerPublicationService(db, None).history(
                ledger_id, owner
            ),
        )
    }
