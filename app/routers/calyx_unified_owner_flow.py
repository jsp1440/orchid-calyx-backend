"""Unified owner-guided Calyx mission-to-supervised-publication flow.

CALYX-470 removes project/ledger/version/hash copying from the owner experience while
keeping human review and explicit publication confirmation as hard governance gates.
The flow is a thin facade over the existing Research Workspace, Brain mission, durable
Reasoning Ledger, eligibility-discovery, publication, and certification services.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.reasoning_ledger.models import ReviewDecision, ReviewOutcome
from app.reasoning_ledger.operational_service import OperationalReasoningLedgerService
from app.reasoning_ledger.routes import _invoke, _subject
from app.reasoning_ledger.serialization import ledger_to_dict
from app.reasoning_publication.eligibility import discover_eligible_ledgers
from app.reasoning_publication.gateway import ExistingKnowledgeGraphPublicationGate
from app.reasoning_publication.service import ReasoningLedgerPublicationService
from app.research_workspace.models import Project
from app.research_workspace.schemas import ProjectCreate
from app.research_workspace.service import (
    ResearchWorkspaceError,
    ResearchWorkspaceService,
)
from app.routers.calyx_operator_workflow import (
    BRAIN_MISSION_SERVICE,
    _mission_for_owner,
    _persist_mission_ledger,
)
from app.security import verify_owner_or_api_key
from runtime.calyx_core_certification import build_calyx_core_certification

router = APIRouter(
    prefix="/mission-control/calyx-owner-flow",
    tags=["calyx-owner-flow"],
)
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]
Db = Annotated[Session, Depends(get_db)]

LAELIA_ANCEPS_QUESTION = (
    "What does the available evidence show about Laelia anceps taxonomy, "
    "distribution, pollination, conservation, and mycorrhizal relationships?"
)
DEMO_PROJECT_TITLE = "Calyx Laelia anceps evidence demonstration"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartOwnerFlowRequest(StrictModel):
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
    max_sources: int = Field(default=20, ge=1, le=100)
    max_execution_steps: int = Field(default=10, ge=1, le=10)
    timeout_seconds: float = Field(default=30, ge=0.1, le=300)


class OwnerFlowReviewRequest(StrictModel):
    outcome: ReviewOutcome
    rationale: str = Field(min_length=1, max_length=4000)


class OwnerFlowPublicationRequest(StrictModel):
    explicit_owner_confirmation: bool
    publication_note: str = Field(default="", max_length=4000)


def _plain_error(code: str) -> str:
    return {
        "MISSION_NOT_FOUND": "That mission is not available in your workspace.",
        "MISSION_LEDGER_UNAVAILABLE": "The mission does not yet have a reviewable Reasoning Ledger.",
        "PROJECT_NOT_FOUND": "The selected research project is not available in your workspace.",
        "LEDGER_NOT_ELIGIBLE": "This mission does not currently have an approved ledger eligible for publication.",
        "MULTIPLE_ELIGIBLE_MATCHES": "More than one eligible version was found for this mission. Review is required before publishing.",
        "EXPLICIT_OWNER_CONFIRMATION_REQUIRED": "Publication requires your explicit confirmation. Nothing was published.",
    }.get(code, "The requested step could not be completed safely. Review the mission status and try again.")


def _raise(status_code: int, code: str, *, detail: str | None = None) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": detail or _plain_error(code),
            "automatic_publication": False,
        },
    )


def _resolve_project_id(
    db: Session,
    owner: str,
    requested_project_id: str | None,
) -> tuple[str, bool]:
    """Resolve a canonical owner project before any Brain mission executes."""
    workspace = ResearchWorkspaceService(db)
    if requested_project_id:
        try:
            project = workspace.get_project(requested_project_id, owner)
        except ResearchWorkspaceError as exc:
            _raise(exc.status, exc.code)
        return str(project["project_id"]), False

    existing = db.scalar(
        select(Project)
        .where(
            Project.owner_subject == owner,
            Project.title == DEMO_PROJECT_TITLE,
            Project.status == "ACTIVE",
            Project.archived_at.is_(None),
        )
        .order_by(Project.created_at.asc())
        .limit(1)
    )
    if existing is not None:
        return str(existing.project_id), False

    try:
        created = workspace.create_project(
            owner,
            ProjectCreate(
                title=DEMO_PROJECT_TITLE,
                description=(
                    "Bounded owner-guided demonstration workspace for the Calyx "
                    "evidence-to-supervised-publication flow."
                ),
                research_question=LAELIA_ANCEPS_QUESTION,
            ),
        )
    except ResearchWorkspaceError as exc:
        _raise(exc.status, exc.code)
    return str(created["project_id"]), True


def _ledger_id(mission: dict[str, Any]) -> str:
    ledger_id = str((mission.get("reasoning_ledger") or {}).get("ledger_id") or "").strip()
    if not ledger_id:
        _raise(409, "MISSION_LEDGER_UNAVAILABLE")
    return ledger_id


def _safe_mission_view(mission: dict[str, Any]) -> dict[str, Any]:
    """Expose the mission scientific state without private reasoning."""
    ledger = mission.get("reasoning_ledger") or {}
    return {
        "mission_id": mission.get("mission_id"),
        "question": mission.get("question"),
        "project_id": mission.get("project_id"),
        "state": mission.get("state"),
        "current_stage": mission.get("current_stage"),
        "steps_executed": mission.get("steps_executed"),
        "plan": mission.get("plan"),
        "evidence": list(mission.get("sources") or []),
        "supporting_evidence": list(mission.get("supporting_evidence") or []),
        "contradicting_evidence": list(mission.get("contradicting_evidence") or []),
        "gaps": list(mission.get("missing_evidence") or []),
        "confidence": mission.get("confidence"),
        "blockers": list(mission.get("blockers") or []),
        "validation": dict(mission.get("validation") or {}),
        "review_status": mission.get("review_status"),
        "publication_eligibility": dict(mission.get("publication_eligibility") or {}),
        "ledger_id": ledger.get("ledger_id"),
        "ledger_version": ledger.get("version"),
        "created_at": mission.get("created_at"),
        "updated_at": mission.get("updated_at"),
        "private_reasoning_exposed": False,
    }


def _durable_mission_view(
    mission: dict[str, Any],
    ledger_payload: dict[str, Any],
    publication_candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Overlay mutable review/publication state from the durable ledger authority."""
    view = _safe_mission_view(mission)
    decisions = list(ledger_payload.get("review_decisions") or [])
    current_version = ledger_payload.get("version")
    current_hash = str(ledger_payload.get("review_content_hash") or "")
    current_decisions = [
        decision
        for decision in decisions
        if decision.get("ledger_version") == current_version
        and str(decision.get("reviewed_content_hash") or "") == current_hash
    ]
    latest = current_decisions[-1] if current_decisions else None
    review_status = (
        str(latest.get("outcome") or "").upper()
        if latest
        else "HUMAN_REVIEW_REQUIRED"
    )
    view["review_status"] = review_status
    view["ledger_id"] = ledger_payload.get("ledger_id") or view.get("ledger_id")
    view["ledger_version"] = current_version
    view["publication_eligibility"] = {
        "eligible": publication_candidate is not None,
        "automatic_publication": False,
        "source": "durable_reasoning_ledger",
        "review_content_hash_current": publication_candidate is not None,
    }
    view["review_state_source"] = "durable_reasoning_ledger"
    view["review_decision_current"] = latest is not None
    return view


def _eligible_for_mission(db: Session, owner: str, mission: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    discovery = discover_eligible_ledgers(db, owner)
    target = _ledger_id(mission)
    matches = [item for item in discovery.get("eligible_ledgers", []) if str(item.get("ledger_id")) == target]
    if len(matches) > 1:
        _raise(409, "MULTIPLE_ELIGIBLE_MATCHES")
    return discovery, matches[0] if matches else None


def _publication_outcome(artifact: dict[str, Any], created: bool) -> dict[str, Any]:
    gate = artifact.get("publication_gate_result") or {}
    graph = gate.get("graph") or {}
    graph_version = graph.get("graph_version_id")
    audit = gate.get("audit") or gate.get("audit_result") or gate.get("validation")
    publication_status = str(artifact.get("publication_status") or "").strip().lower()
    if not created:
        result = "NO_OP_DUPLICATE_REPLAY"
    elif publication_status == "published":
        result = "PUBLISHED"
    elif publication_status == "rejected":
        result = "PUBLICATION_REJECTED"
    else:
        result = "PUBLICATION_NOT_COMPLETED"
    return {
        "result": result,
        "created": created,
        "duplicate_replay_no_op": not created,
        "publication_status": artifact.get("publication_status"),
        "canonical_publication_id": artifact.get("canonical_publication_id"),
        "graph_version": graph_version,
        "graph_version_state": "AVAILABLE" if graph_version is not None else "NOT_RETURNED_BY_PUBLICATION_GATE",
        "audit_outcome": audit,
        "automatic_publication": False,
        "explicit_owner_confirmation": True,
        "owner_copied_identifiers": False,
    }


@router.post("/start", status_code=201)
def start_owner_flow(payload: StartOwnerFlowRequest, request: Request, auth: Auth, db: Db) -> dict[str, Any]:
    owner = _subject(auth)
    project_id, project_created = _invoke(
        db,
        request,
        lambda: _resolve_project_id(db, owner, payload.project_id),
    )
    try:
        mission = BRAIN_MISSION_SERVICE.start(
            question=LAELIA_ANCEPS_QUESTION,
            tenant_id=owner,
            project_id=project_id,
            actor=owner,
            max_sources=payload.max_sources,
            max_steps=payload.max_execution_steps,
            timeout_seconds=payload.timeout_seconds,
        )
        _invoke(db, request, lambda: _persist_mission_ledger(db, owner, mission))
    except HTTPException:
        raise
    except (ValueError, RuntimeError) as exc:
        _raise(422, str(exc), detail="The bounded Laelia anceps mission could not be started safely.")
    return {
        "flow_contract": "calyx-unified-owner-flow/v1",
        "mission": _safe_mission_view(mission),
        "workspace_project": {
            "project_id": project_id,
            "created_for_flow": project_created,
            "owner_copied_project_id": False,
        },
        "next_action": "REVIEW_MISSION",
        "plain_language_status": "The bounded Laelia anceps mission has run to its current governed stopping point. Review its evidence and Reasoning Ledger before making a decision.",
        "automatic_scientific_approval": False,
        "automatic_publication": False,
    }


@router.get("/{mission_id}")
def owner_flow_status(mission_id: str, request: Request, auth: Auth, db: Db) -> dict[str, Any]:
    owner = _subject(auth)
    mission = _mission_for_owner(mission_id, owner)
    ledger_id = _ledger_id(mission)
    ledger = _invoke(db, request, lambda: OperationalReasoningLedgerService(db).current(ledger_id, owner))
    ledger_payload = ledger_to_dict(ledger)
    discovery, candidate = _eligible_for_mission(db, owner, mission)
    certification = build_calyx_core_certification()
    return {
        "flow_contract": "calyx-unified-owner-flow/v1",
        "mission": _durable_mission_view(mission, ledger_payload, candidate),
        "reasoning_ledger": ledger_payload,
        "publication_candidate": candidate,
        "eligible_discovery_result": discovery.get("result"),
        "deployment_certification": {
            "overall_status": certification.get("overall_status"),
            "blockers": certification.get("operational_blockers", {}),
        },
        "next_action": "PUBLISH_WITH_CONFIRMATION" if candidate else "REVIEW_OR_REVISE",
        "owner_must_copy_hash_or_workflow_name": False,
        "automatic_publication": False,
    }


@router.post("/{mission_id}/review")
def review_owner_flow(mission_id: str, payload: OwnerFlowReviewRequest, request: Request, auth: Auth, db: Db) -> dict[str, Any]:
    owner = _subject(auth)
    mission = _mission_for_owner(mission_id, owner)
    ledger_id = _ledger_id(mission)
    current = _invoke(db, request, lambda: OperationalReasoningLedgerService(db).current(ledger_id, owner))
    decision = ReviewDecision(reviewer=owner, outcome=payload.outcome, rationale=payload.rationale)
    reviewed = _invoke(
        db,
        request,
        lambda: OperationalReasoningLedgerService(db).review(
            ledger_id,
            decision,
            owner=owner,
            expected_version=current.version,
        ),
    )
    discovery, candidate = _eligible_for_mission(db, owner, mission)
    reviewed_payload = ledger_to_dict(reviewed)
    return {
        "mission_id": mission_id,
        "mission": _durable_mission_view(mission, reviewed_payload, candidate),
        "reasoning_ledger": reviewed_payload,
        "review_outcome": payload.outcome.value,
        "publication_candidate": candidate,
        "eligible_discovery_result": discovery.get("result"),
        "next_action": "PUBLISH_WITH_CONFIRMATION" if candidate else "REVIEW_COMPLETE_OR_REVISION_REQUIRED",
        "publication_invoked": False,
        "owner_copied_identifiers": False,
        "automatic_publication": False,
    }


@router.get("/{mission_id}/publication-candidate")
def publication_candidate(mission_id: str, auth: Auth, db: Db) -> dict[str, Any]:
    owner = _subject(auth)
    mission = _mission_for_owner(mission_id, owner)
    discovery, candidate = _eligible_for_mission(db, owner, mission)
    return {
        "mission_id": mission_id,
        "result": "MISSION_LEDGER_ELIGIBLE" if candidate else "MISSION_LEDGER_NOT_ELIGIBLE",
        "candidate": candidate,
        "eligible_discovery_result": discovery.get("result"),
        "read_only": True,
        "publication_invoked": False,
        "owner_copied_identifiers": False,
    }


@router.post("/{mission_id}/publish")
def publish_owner_flow(mission_id: str, payload: OwnerFlowPublicationRequest, request: Request, auth: Auth, db: Db) -> dict[str, Any]:
    if not payload.explicit_owner_confirmation:
        _raise(403, "EXPLICIT_OWNER_CONFIRMATION_REQUIRED")
    owner = _subject(auth)
    mission = _mission_for_owner(mission_id, owner)
    _, candidate = _eligible_for_mission(db, owner, mission)
    if candidate is None:
        _raise(409, "LEDGER_NOT_ELIGIBLE")

    artifact, created = _invoke(
        db,
        request,
        lambda: ReasoningLedgerPublicationService(
            db,
            ExistingKnowledgeGraphPublicationGate.from_environment(),
        ).publish(
            str(candidate["ledger_id"]),
            owner=owner,
            expected_version=int(candidate["version"]),
            expected_review_content_hash=str(candidate["review_content_hash"]),
            note=payload.publication_note,
        ),
    )
    outcome = _publication_outcome(artifact, created)
    if outcome["result"] == "NO_OP_DUPLICATE_REPLAY":
        plain_status = "This exact reviewed ledger was already published, so the replay made no change."
    elif outcome["result"] == "PUBLISHED":
        plain_status = "The explicitly confirmed reviewed ledger was submitted through the supervised publication gate and published."
    elif outcome["result"] == "PUBLICATION_REJECTED":
        plain_status = "The supervised publication gate rejected this reviewed ledger. No successful graph publication was recorded."
    else:
        plain_status = "The supervised publication attempt did not report a completed publication. Review the returned status before taking any further action."
    return {
        "mission_id": mission_id,
        **outcome,
        "plain_language_status": plain_status,
    }
