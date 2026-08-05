"""Minimal Mission Control Operator Panel.

Provides a plain-language interface for operators to:
- start a bounded Calyx mission;
- view plan, progress, evidence, contradictions, gaps, confidence, and blockers;
- view the Reasoning Ledger and review state;
- approve, request revision, or reject a ledger;
- discover eligible reviewed ledgers without copying IDs or hashes;
- initiate exactly one supervised publication only after explicit owner confirmation;
- view graph version and publication audit result.

All consequential actions (publication) require explicit owner confirmation.
The panel never asks the operator to copy ledger hashes or workflow names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    LedgerStatus,
    ReasoningLedger,
    ReviewDecision,
    ReviewOutcome,
    UncertaintyMarker,
)
from app.reasoning_ledger.service import (
    InMemoryReasoningLedgerService,
    LedgerNotFoundError,
    ReasoningLedgerService,
)


# ---------------------------------------------------------------------------
# Plain-language error messages.  The panel translates internal codes so the
# operator never needs to understand internal codes or copy ledger hashes.
# ---------------------------------------------------------------------------

_ERROR_MESSAGES: dict[str, str] = {
    "AUTHENTICATED_SUBJECT_REQUIRED": (
        "You must be signed in as the owner to perform this action."
    ),
    "LEDGER_NOT_FOUND": (
        "The requested Reasoning Ledger could not be found."
    ),
    "PUBLICATION_BLOCKED": (
        "Publication is blocked. Please review the open gaps and contradictions "
        "before proceeding."
    ),
    "EXACT_APPROVAL_REQUIRED": (
        "The ledger must have exactly one current approval before it can be "
        "published."
    ),
    "OWNER_CONFIRMATION_REQUIRED": (
        "Publication requires explicit owner confirmation. "
        "Please confirm you want to publish this ledger."
    ),
    "DUPLICATE_PUBLICATION": (
        "This ledger version has already been published. "
        "No duplicate was created."
    ),
}


def friendly_error(code: str) -> str:
    """Return a plain-language description for an internal error code."""
    # Try an exact match first, then a prefix match.
    if code in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[code]
    for prefix, message in _ERROR_MESSAGES.items():
        if code.startswith(prefix):
            return message
    return f"An unexpected error occurred ({code}). Please contact support."


# ---------------------------------------------------------------------------
# Mission brief — compact read-only summary surfaced to the operator.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MissionBrief:
    """Read-only summary of a bounded Calyx mission ledger."""

    ledger_id: str
    title: str
    status: str
    version: int
    plan_entries: int
    evidence_entries: int
    contradiction_entries: int
    unresolved_contradictions: int
    gap_entries: int
    confidence: float | None
    blockers: list[str]
    review_state: str
    last_review_outcome: str | None
    is_eligible_for_publication: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "ledger_id": self.ledger_id,
            "title": self.title,
            "status": self.status,
            "version": self.version,
            "plan_entries": self.plan_entries,
            "evidence_entries": self.evidence_entries,
            "contradiction_entries": self.contradiction_entries,
            "unresolved_contradictions": self.unresolved_contradictions,
            "gap_entries": self.gap_entries,
            "confidence": self.confidence,
            "blockers": self.blockers,
            "review_state": self.review_state,
            "last_review_outcome": self.last_review_outcome,
            "is_eligible_for_publication": self.is_eligible_for_publication,
        }


# ---------------------------------------------------------------------------
# Operator Panel
# ---------------------------------------------------------------------------

class OperatorPanel:
    """Minimal Mission Control Panel for a single Calyx owner session.

    Wraps an in-memory :class:`ReasoningLedgerService` and provides
    operator-facing methods with plain-language feedback.  Publication
    is impossible without an explicit owner confirmation phrase.
    """

    PUBLICATION_CONFIRMATION_PHRASE = "PUBLISH ONE REVIEWED LEDGER"

    def __init__(self, ledger_service: ReasoningLedgerService | None = None) -> None:
        self._service: ReasoningLedgerService = (
            ledger_service if ledger_service is not None else InMemoryReasoningLedgerService()
        )
        # Track publications performed in this session {ledger_id: version}.
        self._publications: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Mission lifecycle
    # ------------------------------------------------------------------

    def start_mission(
        self,
        *,
        owner: str,
        project_id: str,
        title: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new bounded mission ledger and return a brief summary."""
        ledger = self._service.create(
            tenant_id=owner,
            project_id=project_id,
            title=title,
            description=description,
            created_by=owner,
        )
        return {
            "ledger_id": str(ledger.ledger_id),
            "title": ledger.title,
            "status": ledger.status.value,
            "message": f"Mission '{title}' started successfully.",
        }

    def add_evidence(
        self,
        *,
        ledger_id: str,
        owner: str,
        project_id: str,
        text: str,
        kind: LedgerEntryKind = LedgerEntryKind.SUPPORT,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        """Append an evidence entry to the ledger."""
        uncertainty = (
            UncertaintyMarker(confidence=confidence)
            if confidence is not None
            else None
        )
        entry = LedgerEntry(
            kind=kind,
            text=text,
            author=owner,
            tenant_id=owner,
            project_id=project_id,
            uncertainty=uncertainty,
        )
        ledger = self._service.append(
            ledger_id=ledger_id,
            entry=entry,
            actor=owner,
            tenant_id=owner,
        )
        return {
            "ledger_id": str(ledger.ledger_id),
            "version": ledger.version,
            "message": "Evidence recorded.",
        }

    def submit_for_review(
        self, *, ledger_id: str, owner: str, project_id: str
    ) -> dict[str, Any]:
        """Transition the ledger to UNDER_REVIEW status."""
        review_entry = LedgerEntry(
            kind=LedgerEntryKind.OPERATION,
            text="Operator submitted ledger for review.",
            author=owner,
            tenant_id=owner,
            project_id=project_id,
        )
        ledger = self._service.append(
            ledger_id=ledger_id,
            entry=review_entry,
            actor=owner,
            tenant_id=owner,
        )
        return {
            "ledger_id": str(ledger.ledger_id),
            "status": ledger.status.value,
            "message": "Ledger submitted for review. Awaiting owner decision.",
        }

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def approve(
        self,
        *,
        ledger_id: str,
        owner: str,
        rationale: str,
    ) -> dict[str, Any]:
        """Record an approval decision on the ledger."""
        decision = ReviewDecision(
            reviewer=owner,
            outcome=ReviewOutcome.APPROVED,
            rationale=rationale,
        )
        ledger = self._service.review(
            ledger_id=ledger_id,
            decision=decision,
            tenant_id=owner,
        )
        return {
            "ledger_id": str(ledger.ledger_id),
            "status": ledger.status.value,
            "message": "Ledger approved.",
        }

    def request_revision(
        self,
        *,
        ledger_id: str,
        owner: str,
        rationale: str,
    ) -> dict[str, Any]:
        """Record a revision-request decision on the ledger."""
        decision = ReviewDecision(
            reviewer=owner,
            outcome=ReviewOutcome.REQUIRES_REVISION,
            rationale=rationale,
        )
        ledger = self._service.review(
            ledger_id=ledger_id,
            decision=decision,
            tenant_id=owner,
        )
        return {
            "ledger_id": str(ledger.ledger_id),
            "status": ledger.status.value,
            "message": "Revision requested. The ledger is back in progress.",
        }

    def reject(
        self,
        *,
        ledger_id: str,
        owner: str,
        rationale: str,
    ) -> dict[str, Any]:
        """Record a rejection decision on the ledger."""
        decision = ReviewDecision(
            reviewer=owner,
            outcome=ReviewOutcome.REJECTED,
            rationale=rationale,
        )
        ledger = self._service.review(
            ledger_id=ledger_id,
            decision=decision,
            tenant_id=owner,
        )
        return {
            "ledger_id": str(ledger.ledger_id),
            "status": ledger.status.value,
            "message": "Ledger rejected.",
        }

    # ------------------------------------------------------------------
    # Discovery — no hashes or IDs to copy
    # ------------------------------------------------------------------

    def discover_eligible_ledgers(self, *, owner: str) -> dict[str, Any]:
        """Return all ledgers eligible for publication.

        Results include a human-readable title and version.  The operator
        never needs to copy ledger hashes or IDs manually.
        """
        from app.reasoning_ledger import gate as publication_gate

        eligible = []
        for ledger in self._service.list_for_tenant(owner):
            if ledger.is_publishable:
                blockers = publication_gate.evaluate(ledger)
                if not blockers:
                    eligible.append({
                        "ledger_id": str(ledger.ledger_id),
                        "title": ledger.title,
                        "version": ledger.version,
                        "review_content_hash": ledger.review_content_hash,
                        "status": ledger.status.value,
                    })
        return {
            "result": "ELIGIBLE_LEDGER_FOUND" if eligible else "NO_ELIGIBLE_LEDGER",
            "eligible_count": len(eligible),
            "eligible_ledgers": eligible,
            "publication_endpoint_invoked": False,
        }

    # ------------------------------------------------------------------
    # Publication — requires explicit owner confirmation
    # ------------------------------------------------------------------

    def publish(
        self,
        *,
        ledger_id: str,
        owner: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Initiate one supervised publication after explicit owner confirmation.

        The operator never needs to supply a hash or version number; the panel
        resolves those automatically from the current approved state.

        Returns
        -------
        dict with key ``outcome``, one of:
        - ``"PUBLISHED"`` — successful publication; includes ``ledger_id``,
          ``version``, ``graph_version``, and ``automatic_publication``.
        - ``"NO_OP_DUPLICATE"`` — same version already published; includes
          ``ledger_id``, ``version``, ``graph_version`` (None), and
          ``automatic_publication``.
        - ``"REFUSED"`` — owner confirmation phrase not provided; includes
          ``message`` and ``publication_endpoint_invoked``.
        - ``"ERROR"`` — ledger not found or not eligible; includes ``message``
          and ``publication_endpoint_invoked``.
        """
        if confirmation != self.PUBLICATION_CONFIRMATION_PHRASE:
            return {
                "outcome": "REFUSED",
                "message": friendly_error("OWNER_CONFIRMATION_REQUIRED"),
                "publication_endpoint_invoked": False,
            }

        try:
            ledger = self._service.current(ledger_id, tenant_id=owner)
        except (LedgerNotFoundError, KeyError):
            return {
                "outcome": "ERROR",
                "message": friendly_error("LEDGER_NOT_FOUND"),
                "publication_endpoint_invoked": False,
            }

        if not ledger.is_publishable:
            return {
                "outcome": "ERROR",
                "message": friendly_error("PUBLICATION_BLOCKED"),
                "publication_endpoint_invoked": False,
            }

        # Idempotency: duplicate replay is a no-op.
        already_published_version = self._publications.get(ledger_id)
        if already_published_version == ledger.version:
            return {
                "outcome": "NO_OP_DUPLICATE",
                "message": friendly_error("DUPLICATE_PUBLICATION"),
                "ledger_id": ledger_id,
                "version": ledger.version,
                "graph_version": None,
                "automatic_publication": False,
            }

        # Record the publication (in-memory; real deployments call the backend).
        self._publications[ledger_id] = ledger.version

        return {
            "outcome": "PUBLISHED",
            "message": (
                f"Ledger '{ledger.title}' (version {ledger.version}) "
                "published successfully. Graph version recorded."
            ),
            "ledger_id": ledger_id,
            "version": ledger.version,
            "graph_version": f"v{ledger.version}",
            "automatic_publication": False,
        }

    # ------------------------------------------------------------------
    # Inspection / briefing
    # ------------------------------------------------------------------

    def mission_brief(self, *, ledger_id: str, owner: str) -> MissionBrief:
        """Return a compact read-only summary of the mission."""
        from app.reasoning_ledger import gate as publication_gate

        try:
            ledger = self._service.current(ledger_id, tenant_id=owner)
        except (LedgerNotFoundError, KeyError) as exc:
            raise LookupError(friendly_error("LEDGER_NOT_FOUND")) from exc

        plan_entries = sum(
            1 for e in ledger.entries if e.kind is LedgerEntryKind.PLAN
        )
        evidence_entries = sum(
            1 for e in ledger.entries
            if e.kind in (LedgerEntryKind.SUPPORT, LedgerEntryKind.CONCLUSION)
        )
        contradiction_entries = sum(
            1 for e in ledger.entries if e.kind is LedgerEntryKind.COUNTEREVIDENCE
        )
        gap_entries = sum(
            1 for e in ledger.entries if e.kind is LedgerEntryKind.ASSUMPTION
        )
        unresolved = len(ledger.unresolved_conflicts)

        confidence = (
            ledger.min_conclusion_confidence
            if ledger.conclusion_entries
            else None
        )

        blockers_raw = publication_gate.evaluate(ledger)
        blockers = [b.message for b in blockers_raw]

        last_decision = ledger.review_decisions[-1] if ledger.review_decisions else None
        last_outcome = last_decision.outcome.value if last_decision else None

        # review_state reflects the human review perspective: whether the
        # ledger is awaiting review, has been reviewed, or is in progress.
        if ledger.status.value in ("under_review",):
            review_state = "awaiting_review"
        elif last_decision is not None:
            review_state = f"reviewed:{last_outcome}"
        else:
            review_state = "not_yet_reviewed"

        return MissionBrief(
            ledger_id=str(ledger.ledger_id),
            title=ledger.title,
            status=ledger.status.value,
            version=ledger.version,
            plan_entries=plan_entries,
            evidence_entries=evidence_entries,
            contradiction_entries=contradiction_entries,
            unresolved_contradictions=unresolved,
            gap_entries=gap_entries,
            confidence=confidence,
            blockers=blockers,
            review_state=review_state,
            last_review_outcome=last_outcome,
            is_eligible_for_publication=ledger.is_publishable,
        )
