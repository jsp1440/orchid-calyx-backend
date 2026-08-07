from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.brain_mission.routes import ADAPTER as BRAIN_MISSION_ADAPTER
from app.brain_mission.routes import SERVICE as BRAIN_MISSION_SERVICE
from app.database import get_db
from app.reasoning_ledger.models import ReviewDecision, ReviewOutcome
from app.reasoning_ledger.operational_service import OperationalReasoningLedgerService
from app.reasoning_ledger.routes import _invoke, _subject
from app.reasoning_ledger.serialization import ledger_to_dict
from app.reasoning_ledger.service import LedgerNotFoundError, LedgerValidationError
from app.reasoning_publication.eligibility import discover_eligible_ledgers
from app.reasoning_publication.gateway import ExistingKnowledgeGraphPublicationGate
from app.reasoning_publication.service import ReasoningLedgerPublicationService
from app.security import verify_owner_or_api_key
from runtime.calyx_core_certification import build_calyx_core_certification

router = APIRouter(
    prefix="/mission-control/calyx-operator",
    tags=["calyx-operator-workflow"],
)
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]
Db = Annotated[Session, Depends(get_db)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartMissionRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    project_id: str = Field(min_length=1, max_length=200)
    max_sources: int = Field(default=20, ge=1, le=100)
    max_execution_steps: int = Field(default=10, ge=1, le=10)
    timeout_seconds: float = Field(default=30, ge=0.1, le=300)


class LedgerReviewRequest(StrictModel):
    expected_version: int = Field(ge=1)
    outcome: ReviewOutcome
    rationale: str = Field(min_length=1, max_length=4000)


class SupervisedPublicationRequest(StrictModel):
    ledger_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    expected_review_content_hash: str = Field(pattern="^[0-9a-f]{64}$")
    explicit_owner_confirmation: bool
    publication_note: str = Field(default="", max_length=4000)


def _mission_for_owner(mission_id: str, owner: str) -> dict[str, Any]:
    try:
        mission = BRAIN_MISSION_SERVICE.status(mission_id)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "MISSION_NOT_FOUND"}) from exc
    if mission.get("tenant_id") != owner:
        raise HTTPException(404, detail={"code": "MISSION_NOT_FOUND"})
    return mission


def _mission_summary(mission: dict[str, Any]) -> dict[str, Any]:
    ledger = mission.get("reasoning_ledger") or {}
    return {
        "mission_id": mission["mission_id"],
        "question": mission["question"],
        "project_id": mission["project_id"],
        "state": mission["state"],
        "current_stage": mission["current_stage"],
        "steps_executed": mission["steps_executed"],
        "evidence_count": len(mission.get("sources") or []),
        "supporting_evidence_count": len(mission.get("supporting_evidence") or []),
        "contradicting_evidence_count": len(mission.get("contradicting_evidence") or []),
        "missing_evidence": list(mission.get("missing_evidence") or []),
        "confidence": mission.get("confidence"),
        "blockers": list(mission.get("blockers") or []),
        "validation": dict(mission.get("validation") or {}),
        "review_status": mission.get("review_status"),
        "publication_eligibility": dict(mission.get("publication_eligibility") or {}),
        "ledger_id": ledger.get("ledger_id"),
        "ledger_version": ledger.get("version"),
        "automatic_publication": False,
        "created_at": mission.get("created_at"),
        "updated_at": mission.get("updated_at"),
    }


def _persist_mission_ledger(db: Session, owner: str, mission: dict[str, Any]):
    """Synchronize the immutable mission-ledger snapshot into durable governance.

    Mission execution currently builds its governed Reasoning Ledger in the
    Brain adapter's in-memory service. The operator review/publication path is
    intentionally backed by the operational SQL repository. Before exposing a
    ledger ID to an operator, copy only the exact missing immutable revisions
    into that repository. Existing durable entries must be a fingerprint-identical
    prefix of the mission ledger; any divergence fails closed.
    """

    reference = mission.get("reasoning_ledger") or {}
    ledger_id = str(reference.get("ledger_id") or "")
    if not ledger_id:
        raise LedgerValidationError("MISSION_LEDGER_ID_REQUIRED")

    source = BRAIN_MISSION_ADAPTER.ledgers.current(ledger_id, tenant_id=owner)
    service = OperationalReasoningLedgerService(db)
    try:
        current = service.current(ledger_id, owner)
    except LedgerNotFoundError:
        current, _ = service.create(
            owner=owner,
            project_id=source.project_id,
            title=source.title,
            description=source.description,
        )

    if str(current.ledger_id) != str(source.ledger_id):
        raise LedgerValidationError("MISSION_LEDGER_IDENTITY_MISMATCH")
    if (
        current.tenant_id != source.tenant_id
        or current.project_id != source.project_id
        or current.title != source.title
        or current.description != source.description
    ):
        raise LedgerValidationError("MISSION_LEDGER_SCOPE_MISMATCH")
    if len(current.entries) > len(source.entries):
        raise LedgerValidationError("MISSION_LEDGER_DIVERGED")

    for index, durable_entry in enumerate(current.entries):
        if durable_entry.fingerprint != source.entries[index].fingerprint:
            raise LedgerValidationError("MISSION_LEDGER_DIVERGED")

    while len(current.entries) < len(source.entries):
        current = service.append(
            ledger_id,
            source.entries[len(current.entries)],
            owner=owner,
            expected_version=current.version,
        )

    if current.version != source.version:
        raise LedgerValidationError("MISSION_LEDGER_VERSION_MISMATCH")
    return current


@router.post("/missions", status_code=201)
def start_mission(
    payload: StartMissionRequest,
    request: Request,
    auth: Auth,
    db: Db,
) -> dict[str, Any]:
    owner = _subject(auth)
    try:
        mission = BRAIN_MISSION_SERVICE.start(
            question=payload.question,
            tenant_id=owner,
            project_id=payload.project_id,
            actor=owner,
            max_sources=payload.max_sources,
            max_steps=payload.max_execution_steps,
            timeout_seconds=payload.timeout_seconds,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    _invoke(db, request, lambda: _persist_mission_ledger(db, owner, mission))
    return _mission_summary(mission)


@router.get("/missions/{mission_id}")
def mission_status(mission_id: str, auth: Auth) -> dict[str, Any]:
    return _mission_summary(_mission_for_owner(mission_id, _subject(auth)))


@router.get("/ledgers/eligible")
def eligible_ledgers(request: Request, auth: Auth, db: Db) -> dict[str, Any]:
    owner = _subject(auth)
    return _invoke(db, request, lambda: discover_eligible_ledgers(db, owner))


@router.post("/ledgers/{ledger_id}/review")
def review_ledger(
    ledger_id: str,
    payload: LedgerReviewRequest,
    request: Request,
    auth: Auth,
    db: Db,
) -> dict[str, Any]:
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
    return {
        "ledger": ledger_to_dict(ledger),
        "reviewer": owner,
        "automatic_publication": False,
        "publication_invoked": False,
    }


@router.post("/publications")
def supervised_publication(
    payload: SupervisedPublicationRequest,
    request: Request,
    auth: Auth,
    db: Db,
) -> dict[str, Any]:
    if not payload.explicit_owner_confirmation:
        raise HTTPException(
            403,
            detail={
                "code": "EXPLICIT_OWNER_CONFIRMATION_REQUIRED",
                "automatic_publication": False,
            },
        )
    owner = _subject(auth)
    artifact, created = _invoke(
        db,
        request,
        lambda: ReasoningLedgerPublicationService(
            db, ExistingKnowledgeGraphPublicationGate.from_environment()
        ).publish(
            payload.ledger_id,
            owner=owner,
            expected_version=payload.expected_version,
            expected_review_content_hash=payload.expected_review_content_hash,
            note=payload.publication_note,
        ),
    )
    return {
        "created": created,
        "artifact": artifact,
        "automatic_publication": False,
        "explicit_owner_confirmation": True,
    }


@router.get("/publications/{ledger_id}")
def publication_history(
    ledger_id: str,
    request: Request,
    auth: Auth,
    db: Db,
) -> dict[str, Any]:
    owner = _subject(auth)
    items = _invoke(
        db,
        request,
        lambda: ReasoningLedgerPublicationService(db, None).history(ledger_id, owner),
    )
    return {"ledger_id": ledger_id, "items": items, "read_only": True}


@router.get("/graph/version")
def graph_version_status(auth: Auth) -> dict[str, Any]:
    _subject(auth)
    certification = build_calyx_core_certification()
    return {
        "graph_version": None,
        "version_state": "NOT_ASSERTED_BY_OPERATOR_FACADE",
        "operational_status": certification["overall_status"],
        "operational_blockers": certification.get("operational_blockers", {}),
        "production_graph_mutation": False,
        "read_only": True,
    }


@router.get("/panel")
def operator_panel(
    request: Request,
    auth: Auth,
    db: Db,
    mission_id: Annotated[str | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    owner = _subject(auth)
    mission = _mission_summary(_mission_for_owner(mission_id, owner)) if mission_id else None
    eligible = _invoke(db, request, lambda: discover_eligible_ledgers(db, owner))
    certification = build_calyx_core_certification()
    return {
        "owner": owner,
        "mission": mission,
        "eligible_ledgers": eligible,
        "calyx_core_certification": certification,
        "automatic_publication": False,
        "human_review_mandatory": True,
        "production_graph_mutation": False,
        "publication_requires_explicit_owner_confirmation": True,
    }
