from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .models import (
    LedgerEntry,
    LedgerProvenance,
    LedgerValidationError,
    ReviewDecision,
    UncertaintyMarker,
)
from .operational_service import OperationalReasoningLedgerService, ProjectNotFoundError
from .persistence import StaleLedgerVersionError
from .schemas import ConflictResolutionIn, LedgerCreateIn, LedgerEntryIn, ReviewIn
from .serialization import ledger_to_dict
from .service import LedgerNotFoundError

router = APIRouter(prefix="/api/reasoning-ledgers", tags=["reasoning-ledgers"])
project_router = APIRouter(prefix="/api/research/projects", tags=["reasoning-ledgers"])
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]
Db = Annotated[Session, Depends(get_db)]


def _subject(auth: dict) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return subject


def _invoke(db: Session, request: Request, operation):
    try:
        return operation()
    except LedgerNotFoundError as exc:
        db.rollback()
        raise HTTPException(404, detail={"code": "LEDGER_NOT_FOUND"}) from exc
    except StaleLedgerVersionError as exc:
        db.rollback()
        raise HTTPException(
            409,
            detail={"code": "VERSION_CONFLICT", "current_version": exc.current_version},
        ) from exc
    except ProjectNotFoundError as exc:
        db.rollback()
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"}) from exc
    except LedgerValidationError as exc:
        db.rollback()
        code = str(exc) if str(exc).isupper() else "LEDGER_VALIDATION_ERROR"
        raise HTTPException(422, detail={"code": code, "message": str(exc)}) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail={"code": "LEDGER_CONFLICT"}) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            503, detail={"code": "LEDGER_PERSISTENCE_UNAVAILABLE"}
        ) from exc


@router.post("", status_code=201)
def create_ledger(payload: LedgerCreateIn, request: Request, auth: Auth, db: Db):
    owner = _subject(auth)

    def operation():
        ledger, created = OperationalReasoningLedgerService(db).create(
            owner=owner,
            project_id=payload.project_id,
            title=payload.title,
            description=payload.description,
        )
        return {"created": created, "ledger": ledger_to_dict(ledger)}

    return _invoke(db, request, operation)


@router.post("/{ledger_id}/entries", status_code=201)
def append_entry(
    ledger_id: str, payload: LedgerEntryIn, request: Request, auth: Auth, db: Db
):
    owner = _subject(auth)
    current = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).current(ledger_id, owner),
    )
    provenance = (
        LedgerProvenance(
            **payload.provenance.model_dump(),
            rs_project_id=current.project_id,
        )
        if payload.provenance
        else None
    )
    uncertainty = (
        UncertaintyMarker(**payload.uncertainty.model_dump())
        if payload.uncertainty
        else None
    )
    try:
        references = tuple(UUID(value) for value in payload.references_entry_ids)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_ENTRY_REFERENCE"}) from exc
    entry = LedgerEntry(
        kind=payload.kind,
        text=payload.text,
        author=owner,
        tenant_id=owner,
        project_id=current.project_id,
        provenance=provenance,
        uncertainty=uncertainty,
        references_entry_ids=references,
        tags=tuple(payload.tags),
        attributes=payload.attributes,
    )
    ledger = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).append(
            ledger_id,
            entry,
            owner=owner,
            expected_version=payload.expected_version,
        ),
    )
    return ledger_to_dict(ledger)


@router.get("/{ledger_id}")
def get_ledger(ledger_id: str, request: Request, auth: Auth, db: Db):
    owner = _subject(auth)
    return ledger_to_dict(
        _invoke(
            db,
            request,
            lambda: OperationalReasoningLedgerService(db).current(ledger_id, owner),
        )
    )


@router.get("/{ledger_id}/history")
def get_history(ledger_id: str, request: Request, auth: Auth, db: Db):
    owner = _subject(auth)
    result = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).history(ledger_id, owner),
    )
    return {
        "revisions": [ledger_to_dict(item) for item in result["revisions"]],
        "audit_events": result["audit_events"],
    }


@router.post("/{ledger_id}/validate")
def validate_ledger(ledger_id: str, request: Request, auth: Auth, db: Db):
    owner = _subject(auth)
    blockers = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).validate(ledger_id, owner),
    )
    return {"eligible": not blockers, "blocking_reasons": blockers}


@router.post("/{ledger_id}/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    ledger_id: str,
    conflict_id: UUID,
    payload: ConflictResolutionIn,
    request: Request,
    auth: Auth,
    db: Db,
):
    owner = _subject(auth)
    ledger = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).resolve_conflict(
            ledger_id,
            conflict_id,
            owner=owner,
            expected_version=payload.expected_version,
            resolution_state=payload.resolution_state,
            rationale=payload.rationale,
        ),
    )
    return ledger_to_dict(ledger)


@router.post("/{ledger_id}/reviews")
def review_ledger(
    ledger_id: str, payload: ReviewIn, request: Request, auth: Auth, db: Db
):
    owner = _subject(auth)
    decision = ReviewDecision(
        reviewer=owner,
        outcome=payload.outcome,
        rationale=payload.rationale,
    )
    ledger = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).review(
            ledger_id,
            decision,
            owner=owner,
            expected_version=payload.expected_version,
        ),
    )
    return ledger_to_dict(ledger)


@project_router.get("/{project_id}/reasoning-ledgers")
def list_project_ledgers(project_id: str, request: Request, auth: Auth, db: Db):
    owner = _subject(auth)
    ledgers = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).list_for_project(
            project_id, owner
        ),
    )
    return {"items": [ledger_to_dict(ledger) for ledger in ledgers]}
