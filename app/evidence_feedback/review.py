"""Owner review queue and decisions for submitted evidence feedback.

The owner lists submitted cases, reads one case with its event history and the
exact object version the submitter saw, and records a decision:

* ``reject`` -- resolves the case as ``correction_rejected`` with a reason;
* ``needs_governed_review`` -- routes the case to governed (scientific,
  taxonomic, rights or partner) review with a note; the case is not resolved;
* ``accept_trivial`` -- the existing deterministic trivial-correction path
  (``EvidenceFeedbackService.accept_trivial_correction``), unchanged.

Nothing here publishes to the knowledge graph, changes taxonomy or applies a
scientific correction. A non-trivial correction the owner agrees with stays
``governed_review_required``: the scientific publication boundary is
owner-gated and outside code.

Decisions are append-only events. Repeating the same decision is idempotent
(no new event); any other decision on a decided case is an invalid transition.
Submitter and reviewer identities are exposed only as stable opaque references.

Actor references are keyed: ``actor-`` plus the first 24 hex digits of an
HMAC-SHA256 of the identity under a server secret, so a reference cannot be
reversed by hashing guessed login names or emails. The key is derived (with
domain separation) from ``CALYX_EVIDENCE_FEEDBACK_ACTOR_REF_SECRET`` when set,
otherwise from ``CALYX_OWNER_SESSION_SECRET``, which the owner-session-only
review routes already require. References are stable across requests and
processes for the same secret; rotating that secret changes every reference.
With no secret configured the reference is the non-identifying placeholder
``actor-unavailable``, never an unkeyed hash.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from dataclasses import replace
from enum import Enum
from typing import Any

from app.security import get_owner_session_secret

from .models import CaseStatus, Disposition, EvidenceFeedbackCase, content_hash
from .repository import (
    EvidenceFeedbackRepositoryError,
    normalized_key,
    review_order_key,
    validate_free_text,
)
from .service import EvidenceFeedbackService

REVIEW_DEFAULT_LIMIT = 25
REVIEW_MAX_LIMIT = 100
STATEMENT_PREVIEW_CHARS = 280
DUPLICATE_EVENT = "duplicate_submission_suppressed"
REJECTED_EVENT = "owner_decision_rejected"
GOVERNED_REVIEW_EVENT = "owner_decision_needs_governed_review"
PUBLICATION_BOUNDARY = (
    "Review decisions never publish to the knowledge graph, change taxonomy or "
    "apply scientific corrections. Accepted non-trivial corrections remain "
    "governed review required; publication is owner-gated outside this service."
)

OPEN_STATUSES = frozenset({CaseStatus.SUBMITTED, CaseStatus.PENDING_REVIEW})
ACTOR_REF_SECRET_ENV = "CALYX_EVIDENCE_FEEDBACK_ACTOR_REF_SECRET"
ACTOR_REF_UNAVAILABLE = "actor-unavailable"
# Domain separation: the actor-reference key is never the raw session secret.
_ACTOR_REF_KEY_DOMAIN = b"oc-evidence-feedback-actor-ref-key:v2"


class ReviewDecision(str, Enum):
    REJECT = "reject"
    NEEDS_GOVERNED_REVIEW = "needs_governed_review"
    ACCEPT_TRIVIAL = "accept_trivial"


# Status a decision may start from. Governed review happens outside code, so
# its only in-code outcome is a rejection; nothing re-opens a resolved case.
_ALLOWED_FROM: dict[ReviewDecision, frozenset[CaseStatus]] = {
    ReviewDecision.REJECT: OPEN_STATUSES | {CaseStatus.GOVERNED_REVIEW_REQUIRED},
    ReviewDecision.NEEDS_GOVERNED_REVIEW: OPEN_STATUSES,
    ReviewDecision.ACCEPT_TRIVIAL: OPEN_STATUSES,
}


class InvalidCaseTransition(ValueError):
    """The decision is not allowed from the case's current status."""

    code = "INVALID_CASE_TRANSITION"

    def __init__(self, *, current_status: CaseStatus, decision: ReviewDecision) -> None:
        super().__init__(self.code)
        self.current_status = current_status
        self.decision = decision

    def detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "current_status": self.current_status.value,
            "decision": self.decision.value,
        }


def _actor_ref_key() -> bytes | None:
    """The HMAC key for actor references, or ``None`` when no secret is set."""

    for secret in (os.getenv(ACTOR_REF_SECRET_ENV), get_owner_session_secret()):
        if secret and secret.strip():
            return hmac.new(
                secret.encode("utf-8"), _ACTOR_REF_KEY_DOMAIN, hashlib.sha256
            ).digest()
    return None


def actor_ref(actor_id: str | None) -> str | None:
    """A stable opaque reference for a submitter/reviewer identity.

    The raw identity (an owner name, possibly an email) never leaves the
    service; the same identity maps to the same reference for as long as the
    server secret is unchanged. Fails closed to ``actor-unavailable`` when no
    secret is configured.
    """

    if actor_id is None or not str(actor_id).strip():
        return None
    key = _actor_ref_key()
    if key is None:
        return ACTOR_REF_UNAVAILABLE
    digest = hmac.new(
        key, str(actor_id).strip().encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"actor-{digest[:24]}"


def encode_cursor(case: EvidenceFeedbackCase) -> str:
    created_at, case_id = review_order_key(case)
    raw = json.dumps({"c": created_at, "i": case_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at, case_id = value["c"], value["i"]
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError) as exc:
        raise ValueError("INVALID_REVIEW_CURSOR") from exc
    if not isinstance(created_at, str) or not isinstance(case_id, str) or not case_id:
        raise ValueError("INVALID_REVIEW_CURSOR")
    # NUL (which PostgreSQL cannot compare as text) and every other control or
    # non-printable character is bad input, never a store outage.
    if not created_at.isprintable() or not case_id.isprintable():
        raise ValueError("INVALID_REVIEW_CURSOR")
    return created_at, case_id


def review_case_dict(case: EvidenceFeedbackCase) -> dict[str, Any]:
    """The full case record with identities replaced by opaque references."""

    record = case.to_dict()
    record.pop("submitter_id", None)
    record.pop("reviewer_id", None)
    record["submitter_ref"] = actor_ref(case.submitter_id)
    record["reviewer_ref"] = actor_ref(case.reviewer_id)
    return record


def _queue_item(case: EvidenceFeedbackCase, duplicate_count: int) -> dict[str, Any]:
    statement = case.statement
    if len(statement) > STATEMENT_PREVIEW_CHARS:
        statement = statement[:STATEMENT_PREVIEW_CHARS].rstrip() + "…"
    return {
        "case_id": case.case_id,
        "status": case.status.value,
        "disposition": case.disposition.value,
        "review_lane": case.review_lane.value,
        "object_type": case.object_type.value,
        "object_id": case.object_id,
        "object_version_hash": case.object_version_hash,
        "feedback_class": case.feedback_class.value,
        "severity": case.severity,
        "defect_kind": case.defect_kind,
        "page_context": case.page_context,
        "statement_preview": statement,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "duplicate_count": duplicate_count,
        "submitter_ref": actor_ref(case.submitter_id),
    }


def _review_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event.get("event"),
        "timestamp": event.get("timestamp"),
        "actor_ref": actor_ref(event.get("actor_id")),
        "details": dict(event.get("details") or {}),
    }


class EvidenceFeedbackReviewService:
    """Owner-only triage over the cases ``EvidenceFeedbackService`` stores."""

    def __init__(self, service: EvidenceFeedbackService) -> None:
        self.service = service
        self.repository = service.repository

    # -- queue -----------------------------------------------------------------

    def list_cases(
        self,
        *,
        status: CaseStatus | None = None,
        object_type: str | None = None,
        limit: int = REVIEW_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= REVIEW_MAX_LIMIT:
            raise ValueError("INVALID_REVIEW_LIMIT")
        before = decode_cursor(cursor) if cursor else None
        page = self.repository.list_cases(
            status=status.value if status is not None else None,
            object_type=object_type,
            limit=limit + 1,
            before=before,
        )
        has_more = len(page) > limit
        page = page[:limit]
        counts = self.repository.count_case_events(
            [case.case_id for case in page], DUPLICATE_EVENT
        )
        return {
            "items": [_queue_item(case, counts.get(case.case_id, 0)) for case in page],
            "next_cursor": encode_cursor(page[-1]) if has_more and page else None,
            "limit": limit,
        }

    # -- detail ----------------------------------------------------------------

    def allowed_decisions(self, case: EvidenceFeedbackCase) -> list[str]:
        allowed = []
        for decision in ReviewDecision:
            if case.status not in _ALLOWED_FROM[decision]:
                continue
            if (
                decision is ReviewDecision.ACCEPT_TRIVIAL
                and self.service.trivial_correction_blocker(case) is not None
            ):
                continue
            allowed.append(decision.value)
        return allowed

    def _version_or_none(self, object_id: str, version_hash: str | None) -> dict | None:
        if not version_hash:
            return None
        try:
            return self.repository.get_object_version(object_id, version_hash).to_dict()
        except EvidenceFeedbackRepositoryError:
            return None

    def case_detail(self, case_id: str) -> dict[str, Any]:
        case = self.repository.get_case(case_id)
        events = self.repository.list_events(case.case_id)
        object_version = self._version_or_none(case.object_id, case.object_version_hash)
        return {
            "case": review_case_dict(case),
            "duplicate_count": sum(1 for e in events if e.get("event") == DUPLICATE_EVENT),
            "events": [_review_event(event) for event in events],
            "object_version": object_version,
            "object_version_available": object_version is not None,
            "resulting_object_version": self._version_or_none(
                case.object_id, case.resulting_version_hash
            ),
            "allowed_decisions": self.allowed_decisions(case),
            "publication_boundary": PUBLICATION_BOUNDARY,
        }

    # -- decisions -------------------------------------------------------------

    def decide(
        self,
        *,
        case_id: str,
        reviewer_id: str,
        decision: ReviewDecision,
        reason: str | None = None,
        note: str | None = None,
        corrected_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Bad input is refused identically by both stores, before any lock.
        case_key = normalized_key(case_id, code="CASE_ID_REQUIRED")
        validate_free_text(reason, code="REVIEW_REASON_INVALID_CHARACTERS")
        validate_free_text(note, code="REVIEW_NOTE_INVALID_CHARACTERS")
        # One serialized unit per case, the same lock the trivial path takes,
        # so concurrent decisions cannot both apply.
        return self.repository.atomic(
            lambda: self._decide(
                case_id=case_key,
                reviewer_id=reviewer_id,
                decision=decision,
                reason=reason,
                note=note,
                corrected_payload=corrected_payload,
            ),
            lock_key=f"case:{case_key}",
        )

    def _decide(
        self,
        *,
        case_id: str,
        reviewer_id: str,
        decision: ReviewDecision,
        reason: str | None,
        note: str | None,
        corrected_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        case = self.repository.get_case(case_id)
        if self._is_repeat(
            case, decision, reason=reason, note=note, corrected_payload=corrected_payload
        ):
            return self._decision_result(case, decision, idempotent=True)
        if case.status not in _ALLOWED_FROM[decision]:
            raise InvalidCaseTransition(current_status=case.status, decision=decision)

        if decision is ReviewDecision.ACCEPT_TRIVIAL:
            decided = self.service.accept_trivial_correction(
                case_id=case.case_id,
                reviewer_id=reviewer_id,
                corrected_payload=dict(corrected_payload or {}),
            )
            return self._decision_result(decided, decision, idempotent=False)

        now = self.service.clock()
        if decision is ReviewDecision.REJECT:
            text = (reason or "").strip()
            decided = replace(
                case,
                disposition=Disposition.CORRECTION_REJECTED,
                status=CaseStatus.RESOLVED,
                updated_at=now,
                resolution=text,
                reviewer_id=reviewer_id,
            )
            event, details = REJECTED_EVENT, {"reason": text}
        else:
            text = (note or "").strip()
            decided = replace(
                case,
                status=CaseStatus.GOVERNED_REVIEW_REQUIRED,
                updated_at=now,
                reviewer_id=reviewer_id,
            )
            event, details = GOVERNED_REVIEW_EVENT, {"note": text}
        self.repository.save_case(decided)
        self.repository.append_event(
            case_id=case.case_id,
            event=event,
            timestamp=now,
            actor_id=reviewer_id,
            details={
                **details,
                "previous_status": case.status.value,
                "status": decided.status.value,
                "disposition": decided.disposition.value,
            },
        )
        return self._decision_result(decided, decision, idempotent=False)

    def _is_repeat(
        self,
        case: EvidenceFeedbackCase,
        decision: ReviewDecision,
        *,
        reason: str | None,
        note: str | None,
        corrected_payload: dict[str, Any] | None,
    ) -> bool:
        if decision is ReviewDecision.REJECT:
            return (
                case.status is CaseStatus.RESOLVED
                and case.disposition is Disposition.CORRECTION_REJECTED
                and case.resolution == (reason or "").strip()
            )
        if decision is ReviewDecision.ACCEPT_TRIVIAL:
            return (
                case.status is CaseStatus.RESOLVED
                and case.disposition is Disposition.CORRECTION_ACCEPTED
                and corrected_payload is not None
                and case.resulting_version_hash == content_hash(corrected_payload)
            )
        if case.status is not CaseStatus.GOVERNED_REVIEW_REQUIRED:
            return False
        routed = [
            event
            for event in self.repository.list_events(case.case_id)
            if event.get("event") == GOVERNED_REVIEW_EVENT
        ]
        return bool(routed) and (routed[-1].get("details") or {}).get("note") == (
            note or ""
        ).strip()

    def _decision_result(
        self, case: EvidenceFeedbackCase, decision: ReviewDecision, *, idempotent: bool
    ) -> dict[str, Any]:
        return {
            "decision": decision.value,
            "idempotent": idempotent,
            "case": review_case_dict(case),
            "allowed_decisions": self.allowed_decisions(case),
            "publication_boundary": PUBLICATION_BOUNDARY,
        }
