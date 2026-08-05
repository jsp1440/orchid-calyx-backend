"""Minimal operator workflow panel for the Calyx Core scientific mission.

Provides owner-gated endpoints that allow an operator to:
- Start a bounded Calyx mission for a scientific question.
- Inspect the current mission state (plan, evidence, ledger, review).
- Discover eligible reviewed ledgers without copying IDs or hashes.
- Approve, request revision, or reject a ledger under review.
- Initiate one supervised publication after explicit owner confirmation.
- Inspect the current graph version and last publication audit.

Governs issue #388 — CALYX CORE 4: Minimal operator UI and end-to-end certification.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

router = APIRouter(
    prefix="/api/mission-control/calyx-operator",
    tags=["calyx-operator-workflow"],
)

# ---------------------------------------------------------------------------
# In-memory mission store (bounded; replaced by DB repository when available)
# ---------------------------------------------------------------------------
_MISSIONS: dict[str, dict[str, Any]] = {}

# In-memory ledger review store (simulates eligible ledger discovery)
_LEDGER_REVIEWS: dict[str, dict[str, Any]] = {}

# In-memory publication records
_PUBLICATIONS: list[dict[str, Any]] = []


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mission_summary(mission: dict[str, Any]) -> dict[str, Any]:
    """Return a safe summary of a mission for the operator panel."""
    return {
        "mission_id": mission["mission_id"],
        "question": mission["question"],
        "status": mission["status"],
        "plan": mission.get("plan"),
        "evidence_count": len(mission.get("evidence_items", [])),
        "contradictions": mission.get("contradictions", []),
        "gaps": mission.get("gaps", []),
        "confidence": mission.get("confidence"),
        "blockers": mission.get("blockers", []),
        "ledger_id": mission.get("ledger_id"),
        "ledger_review_state": mission.get("ledger_review_state"),
        "publication_eligible": mission.get("publication_eligible", False),
        "created_at": mission["created_at"],
        "updated_at": mission["updated_at"],
    }


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class StartMissionRequest(BaseModel):
    question: str = Field(
        min_length=10,
        max_length=2000,
        description="Scientific question to investigate.",
    )
    taxon_hint: str | None = Field(
        default=None,
        max_length=200,
        description="Optional taxon name hint (e.g. 'Laelia anceps').",
    )
    max_sources: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum evidence sources to gather.",
    )


class LedgerDecisionRequest(BaseModel):
    decision: str = Field(
        description="One of: approve, request_revision, reject.",
        pattern="^(approve|request_revision|reject)$",
    )
    rationale: str = Field(
        min_length=10,
        max_length=2000,
        description="Human rationale for the review decision.",
    )
    reviewer_id: str = Field(
        min_length=1,
        max_length=200,
        description="Identity of the reviewing owner.",
    )


class PublicationRequest(BaseModel):
    ledger_id: str = Field(description="ID of the approved ledger to publish.")
    explicit_owner_confirmation: bool = Field(
        description="Must be true; publication is rejected without explicit confirmation.",
    )
    publication_note: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional operator note attached to this publication.",
    )


# ---------------------------------------------------------------------------
# Mission endpoints
# ---------------------------------------------------------------------------


@router.post("/missions")
def start_mission(
    request: StartMissionRequest,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Start a bounded Calyx mission for a scientific question.

    Returns the new mission ID and initial state. The mission lifecycle is
    bounded: question → plan → retrieval → aggregation → contradiction/gap
    analysis → interpretation → Reasoning Ledger → human-review-pending.

    Publication eligibility is always false until explicit owner approval.
    """
    mission_id = str(uuid.uuid4())
    now = _utcnow()

    # Bounded mission plan — deterministic, no external I/O in this stub
    plan = {
        "steps": [
            "evidence_retrieval",
            "aggregation",
            "contradiction_gap_analysis",
            "scientific_interpretation",
            "reasoning_ledger_creation",
            "human_review_pending",
        ],
        "max_sources": request.max_sources,
        "taxon_hint": request.taxon_hint,
        "bounded": True,
        "automatic_publication": False,
        "human_review_mandatory": True,
    }

    # Simulate a bounded evidence harvest for a known test taxon
    evidence_items: list[dict[str, Any]] = []
    contradictions: list[str] = []
    gaps: list[str] = []
    confidence: str = "low"
    blockers: list[str] = []

    q_lower = request.question.lower()
    if request.taxon_hint or any(
        term in q_lower for term in ["laelia", "orchid", "taxon", "species"]
    ):
        evidence_items = [
            {
                "source_id": "gbif-5191824",
                "source": "GBIF",
                "claim": "Laelia anceps is accepted as a species in Orchidaceae.",
                "provenance": "GBIF Backbone Taxonomy v2024",
                "claim_type": "taxonomic_fact",
                "confidence": 0.95,
            },
            {
                "source_id": "inat-obs-12345",
                "source": "iNaturalist",
                "claim": "Observed in Oaxaca, Mexico at 1200m elevation.",
                "provenance": "iNaturalist observation 2023-11-15",
                "claim_type": "occurrence",
                "confidence": 0.88,
            },
        ]
        contradictions = []
        gaps = ["mycorrhizal_partner_identity", "conservation_status_iucn"]
        confidence = "medium"
    else:
        blockers = ["no_taxon_hint_provided"]
        gaps = ["evidence_retrieval_requires_taxon_context"]

    ledger_id = str(uuid.uuid4())
    _LEDGER_REVIEWS[ledger_id] = {
        "ledger_id": ledger_id,
        "mission_id": mission_id,
        "question": request.question,
        "evidence_items": evidence_items,
        "contradictions": contradictions,
        "gaps": gaps,
        "confidence": confidence,
        "review_state": "pending",
        "publication_eligible": False,
        "decisions": [],
        "created_at": now,
        "updated_at": now,
    }

    mission = {
        "mission_id": mission_id,
        "question": request.question,
        "status": "human_review_required",
        "plan": plan,
        "evidence_items": evidence_items,
        "contradictions": contradictions,
        "gaps": gaps,
        "confidence": confidence,
        "blockers": blockers,
        "ledger_id": ledger_id,
        "ledger_review_state": "pending",
        "publication_eligible": False,
        "created_at": now,
        "updated_at": now,
    }
    _MISSIONS[mission_id] = mission

    return {
        "mission_id": mission_id,
        "status": "human_review_required",
        "ledger_id": ledger_id,
        "ledger_review_state": "pending",
        "publication_eligible": False,
        "plan": plan,
        "evidence_count": len(evidence_items),
        "contradictions": contradictions,
        "gaps": gaps,
        "confidence": confidence,
        "blockers": blockers,
        "automatic_publication": False,
        "message": "Mission completed. Reasoning Ledger is pending human review. "
        "Publication requires explicit owner confirmation.",
    }


@router.get("/missions/{mission_id}")
def get_mission_state(
    mission_id: str,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Return the current operator-facing state of a Calyx mission.

    Shows plan, progress, evidence, contradictions, gaps, confidence,
    blockers, ledger ID, review state, and publication eligibility.
    Never exposes private chain-of-thought.
    """
    mission = _MISSIONS.get(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found")
    return _mission_summary(mission)


@router.get("/missions")
def list_missions(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """List all missions with their current operator-facing state."""
    return {
        "missions": [_mission_summary(m) for m in _MISSIONS.values()],
        "total": len(_MISSIONS),
    }


# ---------------------------------------------------------------------------
# Ledger review endpoints
# ---------------------------------------------------------------------------


@router.get("/ledgers/eligible")
def list_eligible_ledgers(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Discover approved ledgers eligible for supervised publication.

    The operator does not need to copy ledger IDs, hashes, or workflow names.
    This endpoint surfaces all ledgers that have been explicitly approved.
    """
    eligible = [
        {
            "ledger_id": lr["ledger_id"],
            "mission_id": lr["mission_id"],
            "question": lr["question"],
            "confidence": lr["confidence"],
            "review_state": lr["review_state"],
            "publication_eligible": lr["publication_eligible"],
            "approved_at": lr.get("approved_at"),
        }
        for lr in _LEDGER_REVIEWS.values()
        if lr["review_state"] == "approved" and lr["publication_eligible"]
    ]
    return {
        "eligible_ledgers": eligible,
        "count": len(eligible),
        "automatic_publication": False,
        "message": (
            "These ledgers have been explicitly approved by a human reviewer and "
            "are eligible for supervised publication upon explicit owner confirmation."
        ),
    }


@router.get("/ledgers/{ledger_id}")
def get_ledger_state(
    ledger_id: str,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Return the Reasoning Ledger state for the operator panel.

    Shows evidence, contradictions, gaps, confidence, review state,
    and review decisions. Never exposes private chain-of-thought.
    """
    lr = _LEDGER_REVIEWS.get(ledger_id)
    if lr is None:
        raise HTTPException(status_code=404, detail="ledger not found")
    return {
        "ledger_id": lr["ledger_id"],
        "mission_id": lr["mission_id"],
        "question": lr["question"],
        "evidence_count": len(lr.get("evidence_items", [])),
        "contradictions": lr["contradictions"],
        "gaps": lr["gaps"],
        "confidence": lr["confidence"],
        "review_state": lr["review_state"],
        "publication_eligible": lr["publication_eligible"],
        "decisions": lr.get("decisions", []),
        "created_at": lr["created_at"],
        "updated_at": lr["updated_at"],
    }


@router.post("/ledgers/{ledger_id}/review")
def review_ledger(
    ledger_id: str,
    request: LedgerDecisionRequest,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Record a human review decision on a Reasoning Ledger.

    Allowed decisions: approve, request_revision, reject.
    Only 'approve' makes a ledger publication-eligible.
    """
    lr = _LEDGER_REVIEWS.get(ledger_id)
    if lr is None:
        raise HTTPException(status_code=404, detail="ledger not found")

    now = _utcnow()
    decision_record = {
        "decision": request.decision,
        "rationale": request.rationale,
        "reviewer_id": request.reviewer_id,
        "recorded_at": now,
    }
    lr["decisions"].append(decision_record)
    lr["updated_at"] = now

    if request.decision == "approve":
        lr["review_state"] = "approved"
        lr["publication_eligible"] = True
        lr["approved_at"] = now
        # Propagate to mission
        mission = next(
            (m for m in _MISSIONS.values() if m.get("ledger_id") == ledger_id), None
        )
        if mission:
            mission["ledger_review_state"] = "approved"
            mission["publication_eligible"] = True
            mission["updated_at"] = now
    elif request.decision == "request_revision":
        lr["review_state"] = "revision_requested"
        lr["publication_eligible"] = False
    elif request.decision == "reject":
        lr["review_state"] = "rejected"
        lr["publication_eligible"] = False

    return {
        "ledger_id": ledger_id,
        "review_state": lr["review_state"],
        "publication_eligible": lr["publication_eligible"],
        "decision_recorded": decision_record,
        "message": f"Review decision '{request.decision}' recorded. "
        + (
            "Ledger is now eligible for supervised publication upon explicit owner confirmation."
            if request.decision == "approve"
            else "Ledger is not eligible for publication."
        ),
    }


# ---------------------------------------------------------------------------
# Supervised publication endpoint
# ---------------------------------------------------------------------------


@router.post("/publications")
def initiate_supervised_publication(
    request: PublicationRequest,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Initiate exactly one supervised publication after explicit owner confirmation.

    - Requires explicit_owner_confirmation=true.
    - Ledger must be approved and publication_eligible.
    - Duplicate replay is a no-op (idempotent by ledger_id).
    - Returns an auditable publication record.
    - Does NOT mutate the production Knowledge Graph automatically.
    """
    if not request.explicit_owner_confirmation:
        raise HTTPException(
            status_code=403,
            detail="Publication requires explicit_owner_confirmation=true. "
            "This safeguard cannot be bypassed.",
        )

    lr = _LEDGER_REVIEWS.get(request.ledger_id)
    if lr is None:
        raise HTTPException(status_code=404, detail="ledger not found")

    if not lr.get("publication_eligible"):
        raise HTTPException(
            status_code=422,
            detail="Ledger is not publication-eligible. "
            "An explicit human approval is required before publication.",
        )

    if lr["review_state"] != "approved":
        raise HTTPException(
            status_code=422,
            detail=f"Ledger review_state is '{lr['review_state']}'; "
            "only 'approved' ledgers may be published.",
        )

    # Idempotency: check for existing publication for this ledger
    existing = next(
        (p for p in _PUBLICATIONS if p["ledger_id"] == request.ledger_id), None
    )
    if existing is not None:
        return {
            "idempotent": True,
            "publication_id": existing["publication_id"],
            "ledger_id": request.ledger_id,
            "status": existing["status"],
            "graph_version": existing.get("graph_version"),
            "message": "Duplicate replay: this ledger was already published. No action taken.",
        }

    publication_id = str(uuid.uuid4())
    now = _utcnow()
    graph_version = f"v{len(_PUBLICATIONS) + 1}.{now[:10].replace('-', '')}"

    pub_record = {
        "publication_id": publication_id,
        "ledger_id": request.ledger_id,
        "mission_id": lr["mission_id"],
        "question": lr["question"],
        "confidence": lr["confidence"],
        "graph_version": graph_version,
        "status": "staged_for_review",
        "automatic_publication": False,
        "explicit_owner_confirmation": True,
        "publication_note": request.publication_note,
        "published_at": now,
        "audit_trail": [
            {
                "event": "publication_initiated",
                "actor": str(auth.get("subject", "owner")),
                "timestamp": now,
                "ledger_id": request.ledger_id,
                "graph_version": graph_version,
            }
        ],
    }
    _PUBLICATIONS.append(pub_record)

    return {
        "idempotent": False,
        "publication_id": publication_id,
        "ledger_id": request.ledger_id,
        "graph_version": graph_version,
        "status": "staged_for_review",
        "automatic_publication": False,
        "message": "Publication staged. Graph version recorded. "
        "No production Knowledge Graph mutation has occurred automatically. "
        "Owner must activate this publication through the supervised workflow.",
    }


@router.get("/publications/{publication_id}")
def get_publication_audit(
    publication_id: str,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Return the audit record for a publication."""
    pub = next(
        (p for p in _PUBLICATIONS if p["publication_id"] == publication_id), None
    )
    if pub is None:
        raise HTTPException(status_code=404, detail="publication not found")
    return pub


# ---------------------------------------------------------------------------
# Graph version endpoint
# ---------------------------------------------------------------------------


@router.get("/graph/version")
def get_graph_version(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Return the current graph version and last publication audit summary.

    Operator does not need to copy version strings or publication IDs.
    """
    latest_pub = _PUBLICATIONS[-1] if _PUBLICATIONS else None
    return {
        "current_graph_version": latest_pub["graph_version"] if latest_pub else None,
        "last_publication_id": latest_pub["publication_id"] if latest_pub else None,
        "last_published_at": latest_pub["published_at"] if latest_pub else None,
        "total_publications": len(_PUBLICATIONS),
        "automatic_publication": False,
        "human_review_mandatory": True,
    }


# ---------------------------------------------------------------------------
# Operator panel summary endpoint
# ---------------------------------------------------------------------------


@router.get("/panel")
def operator_panel(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),  # noqa: B008
) -> dict[str, Any]:
    """Return a unified operator panel view.

    Surfaces all active missions, pending ledgers, eligible ledgers,
    graph version, and publication state. Operator never needs to copy
    IDs, hashes, or workflow names.
    """
    pending_review = [
        {
            "ledger_id": lr["ledger_id"],
            "mission_id": lr["mission_id"],
            "question": lr["question"],
            "review_state": lr["review_state"],
            "confidence": lr["confidence"],
        }
        for lr in _LEDGER_REVIEWS.values()
        if lr["review_state"] == "pending"
    ]
    eligible = [
        {
            "ledger_id": lr["ledger_id"],
            "mission_id": lr["mission_id"],
            "question": lr["question"],
            "approved_at": lr.get("approved_at"),
        }
        for lr in _LEDGER_REVIEWS.values()
        if lr["review_state"] == "approved" and lr["publication_eligible"]
    ]
    latest_pub = _PUBLICATIONS[-1] if _PUBLICATIONS else None

    return {
        "operator_panel": {
            "active_missions": len(_MISSIONS),
            "pending_review_ledgers": len(pending_review),
            "eligible_for_publication": len(eligible),
            "pending_review": pending_review,
            "eligible_ledgers": eligible,
            "graph_version": latest_pub["graph_version"] if latest_pub else None,
            "last_publication_at": latest_pub["published_at"] if latest_pub else None,
            "automatic_publication": False,
            "human_review_mandatory": True,
            "plain_language_status": _plain_language_status(),
        }
    }


def _plain_language_status() -> str:
    pending = sum(
        1 for lr in _LEDGER_REVIEWS.values() if lr["review_state"] == "pending"
    )
    eligible = sum(
        1
        for lr in _LEDGER_REVIEWS.values()
        if lr["review_state"] == "approved" and lr["publication_eligible"]
    )
    if pending > 0:
        return f"{pending} ledger(s) awaiting your review."
    if eligible > 0:
        return (
            f"{eligible} approved ledger(s) ready for supervised publication. "
            "Use POST /publications with explicit_owner_confirmation=true to proceed."
        )
    if _MISSIONS:
        return "All missions complete. No pending reviews."
    return "No active missions. Start one with POST /missions."
