"""Deterministic triage and governed correction service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from .models import (
    CaseStatus,
    Disposition,
    EvidenceFeedbackCase,
    EvidenceObjectVersion,
    FeedbackClass,
    ObjectType,
    ReviewLane,
    content_hash,
    feedback_fingerprint,
)
from .repository import (
    EvidenceFeedbackRepository,
    EvidenceFeedbackRepositoryError,
    normalized_key,
    validate_free_text,
    validate_label,
)

Clock = Callable[[], str]

# Member-registered snapshots live in their own object namespace, keyed by the
# type the member CLAIMED, so they can never collide with, block or pre-empt a
# canonical (owner / API-key) registration, nor one another. The prefix is
# reserved: no caller may register or submit against it directly.
MEMBER_SNAPSHOT_PREFIX = "member-snapshot:"
TYPE_SOURCE_REGISTERED = "registered"
TYPE_SOURCE_MEMBER_CLAIMED = "member_claimed"
MEMBER_ROLE = "member"


def member_snapshot_object_id(object_type: ObjectType, object_id: str) -> str:
    return f"{MEMBER_SNAPSHOT_PREFIX}{object_type.value}:{object_id.strip()}"


def _refuse_reserved_object_id(object_id: str) -> None:
    if object_id.strip().startswith(MEMBER_SNAPSHOT_PREFIX):
        raise ValueError("OBJECT_ID_RESERVED")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    case: EvidenceFeedbackCase
    created: bool
    duplicate_of: str | None = None


class EvidenceFeedbackService:
    """Routes feedback without granting authority to alter scientific truth."""

    def __init__(
        self,
        repository: EvidenceFeedbackRepository,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self.repository = repository
        self.clock = clock

    def register_object(
        self,
        *,
        object_id: str,
        object_type: ObjectType,
        payload: dict[str, Any],
        previous_version_hash: str | None = None,
        registered_by_role: str | None = None,
    ) -> EvidenceObjectVersion:
        _refuse_reserved_object_id(object_id)
        return self._save_version(
            object_id=object_id,
            object_type=object_type,
            payload=payload,
            previous_version_hash=previous_version_hash,
            registered_by_role=registered_by_role,
        )

    def register_member_snapshot(
        self,
        *,
        object_id: str,
        object_type: ObjectType,
        payload: dict[str, Any],
    ) -> tuple[EvidenceObjectVersion, bool]:
        """Record what a member says they saw; returns ``(version, provisional)``.

        When a canonical version with this content already exists, nothing is
        written and that version is returned (``provisional`` False): the
        member's case will bind to it and take its trusted type. Otherwise the
        snapshot is stored provisionally in the member namespace, where it can
        never block a later canonical registration of the same content.
        """

        _refuse_reserved_object_id(object_id)
        normalized_key(object_id, code="OBJECT_ID_REQUIRED")
        canonical = self._canonical_or_none(object_id, content_hash(payload))
        if canonical is not None:
            return canonical, False
        snapshot = self._save_version(
            object_id=member_snapshot_object_id(object_type, object_id),
            object_type=object_type,
            payload=payload,
            previous_version_hash=None,
            registered_by_role=MEMBER_ROLE,
        )
        return snapshot, True

    def _canonical_or_none(
        self, object_id: str, version_hash: str
    ) -> EvidenceObjectVersion | None:
        try:
            return self.repository.get_object_version(object_id, version_hash)
        except EvidenceFeedbackRepositoryError as exc:
            if str(exc) == "OBJECT_VERSION_NOT_FOUND":
                return None
            raise

    def _save_version(
        self,
        *,
        object_id: str,
        object_type: ObjectType,
        payload: dict[str, Any],
        previous_version_hash: str | None,
        registered_by_role: str | None,
    ) -> EvidenceObjectVersion:
        now = self.clock()
        version = EvidenceObjectVersion(
            object_id=object_id.strip(),
            object_type=object_type,
            version_hash=content_hash(payload),
            payload=payload,
            created_at=now,
            previous_version_hash=previous_version_hash,
            registered_by_role=registered_by_role,
        )
        return self.repository.save_object_version(version)

    def submit(
        self,
        *,
        object_id: str,
        object_version_hash: str,
        object_type: ObjectType,
        page_context: str,
        feedback_class: FeedbackClass,
        statement: str,
        proposed_replacement: str | None = None,
        citation: str | None = None,
        submitter_id: str | None = None,
        source_partner_id: str | None = None,
        defect_kind: str | None = None,
        severity: str = "normal",
        submitter_role: str | None = None,
    ) -> SubmissionResult:
        _refuse_reserved_object_id(object_id)
        if not statement.strip():
            raise ValueError("FEEDBACK_STATEMENT_REQUIRED")
        # Refused identically by both stores (422), before any store access.
        for name, text in (
            ("STATEMENT", statement),
            ("PAGE_CONTEXT", page_context),
            ("PROPOSED_REPLACEMENT", proposed_replacement),
            ("CITATION", citation),
        ):
            validate_free_text(text, code=f"{name}_INVALID_CHARACTERS")
        for name, label in (
            ("SOURCE_PARTNER_ID", source_partner_id),
            ("DEFECT_KIND", defect_kind),
            ("SEVERITY", severity),
        ):
            validate_label(label, code=f"{name}_INVALID_CHARACTERS")
        normalized_key(object_id, code="OBJECT_ID_REQUIRED")
        if submitter_role == MEMBER_ROLE:
            # A member's claimed type never decides triage when a canonical
            # version exists: that version's type is the trusted one.
            canonical = self._canonical_or_none(object_id, object_version_hash)
            if canonical is not None:
                object_type, type_source = canonical.object_type, TYPE_SOURCE_REGISTERED
            else:
                self.repository.get_object_version(
                    member_snapshot_object_id(object_type, object_id),
                    object_version_hash,
                )
                type_source = TYPE_SOURCE_MEMBER_CLAIMED
        else:
            persisted = self.repository.get_object_version(
                object_id,
                object_version_hash,
            )
            if persisted.object_type is not object_type:
                raise ValueError("OBJECT_TYPE_MISMATCH")
            type_source = TYPE_SOURCE_REGISTERED

        fingerprint = feedback_fingerprint(
            object_id=object_id,
            object_version_hash=object_version_hash,
            object_type=object_type,
            feedback_class=feedback_class,
            statement=statement,
            proposed_replacement=proposed_replacement,
            citation=citation,
        )
        # The duplicate check and the write are one serialized unit per
        # fingerprint, so concurrent identical submissions yield one case and
        # the case is never stored without its ``case_submitted`` event.
        return self.repository.atomic(
            lambda: self._submit_new_or_duplicate(
                fingerprint=fingerprint,
                object_id=object_id,
                object_version_hash=object_version_hash,
                object_type=object_type,
                page_context=page_context,
                feedback_class=feedback_class,
                statement=statement,
                proposed_replacement=proposed_replacement,
                citation=citation,
                submitter_id=submitter_id,
                source_partner_id=source_partner_id,
                defect_kind=defect_kind,
                severity=severity,
                submitter_role=submitter_role,
                object_type_source=type_source,
            ),
            lock_key=f"fingerprint:{fingerprint}",
        )

    def _submit_new_or_duplicate(
        self,
        *,
        fingerprint: str,
        object_id: str,
        object_version_hash: str,
        object_type: ObjectType,
        page_context: str,
        feedback_class: FeedbackClass,
        statement: str,
        proposed_replacement: str | None,
        citation: str | None,
        submitter_id: str | None,
        source_partner_id: str | None,
        defect_kind: str | None,
        severity: str,
        submitter_role: str | None = None,
        object_type_source: str | None = None,
    ) -> SubmissionResult:
        existing = self.repository.find_by_fingerprint(fingerprint)
        if existing is not None:
            self.repository.append_event(
                case_id=existing.case_id,
                event="duplicate_submission_suppressed",
                timestamp=self.clock(),
                actor_id=submitter_id,
                details={"duplicate_of": existing.case_id},
            )
            return SubmissionResult(
                case=existing,
                created=False,
                duplicate_of=existing.case_id,
            )

        disposition, lane = self._triage(
            object_type=object_type,
            feedback_class=feedback_class,
            proposed_replacement=proposed_replacement,
            source_partner_id=source_partner_id,
            defect_kind=defect_kind,
        )
        if (
            object_type_source == TYPE_SOURCE_MEMBER_CLAIMED
            and disposition is Disposition.AUTO_CORRECTABLE
        ):
            # A type only the member claimed never opens the deterministic
            # path: the case goes to scientific review until the owner confirms.
            disposition, lane = (
                Disposition.NEEDS_SCIENTIFIC_REVIEW,
                ReviewLane.SCIENTIFIC,
            )
        now = self.clock()
        case = EvidenceFeedbackCase(
            case_id=f"efc-{fingerprint[:24]}",
            fingerprint=fingerprint,
            object_id=object_id.strip(),
            object_version_hash=object_version_hash.strip().casefold(),
            object_type=object_type,
            page_context=page_context.strip(),
            feedback_class=feedback_class,
            statement=statement.strip(),
            disposition=disposition,
            status=CaseStatus.PENDING_REVIEW,
            review_lane=lane,
            created_at=now,
            updated_at=now,
            proposed_replacement=(
                proposed_replacement.strip() if proposed_replacement else None
            ),
            citation=citation.strip() if citation else None,
            submitter_id=submitter_id,
            source_partner_id=source_partner_id,
            defect_kind=defect_kind,
            severity=severity,
            submitter_role=submitter_role,
            object_type_source=object_type_source,
        )
        self.repository.save_case(case)
        self.repository.append_event(
            case_id=case.case_id,
            event="case_submitted",
            timestamp=now,
            actor_id=submitter_id,
            details={
                "disposition": disposition.value,
                "review_lane": lane.value,
                "object_version_hash": case.object_version_hash,
            },
        )
        return SubmissionResult(case=case, created=True)

    def accept_trivial_correction(
        self,
        *,
        case_id: str,
        reviewer_id: str,
        corrected_payload: dict[str, Any],
    ) -> EvidenceFeedbackCase:
        # Serialized per case so two reviewers cannot both resolve it. The id
        # is validated before it becomes a lock key.
        case_key = normalized_key(case_id, code="CASE_ID_REQUIRED")
        return self.repository.atomic(
            lambda: self._accept_trivial_correction(
                case_id=case_key,
                reviewer_id=reviewer_id,
                corrected_payload=corrected_payload,
            ),
            lock_key=f"case:{case_key}",
        )

    def _accept_trivial_correction(
        self,
        *,
        case_id: str,
        reviewer_id: str,
        corrected_payload: dict[str, Any],
    ) -> EvidenceFeedbackCase:
        case = self.repository.get_case(case_id)
        blocker = self.trivial_correction_blocker(case)
        if blocker is not None:
            raise ValueError(blocker)
        previous = self.repository.get_object_version(
            case.object_id,
            case.object_version_hash,
        )
        current_versions = self.repository.list_object_versions(case.object_id)
        if current_versions and all(
            item.version_hash != previous.version_hash for item in current_versions
        ):
            raise ValueError("STALE_OBJECT_VERSION")

        new_version = self.register_object(
            object_id=case.object_id,
            object_type=case.object_type,
            payload=corrected_payload,
            previous_version_hash=previous.version_hash,
        )
        now = self.clock()
        resolved = replace(
            case,
            disposition=Disposition.CORRECTION_ACCEPTED,
            status=CaseStatus.RESOLVED,
            updated_at=now,
            resolution="deterministic trivial correction accepted",
            resulting_version_hash=new_version.version_hash,
            reviewer_id=reviewer_id,
        )
        self.repository.save_case(resolved)
        self.repository.append_event(
            case_id=case.case_id,
            event="correction_accepted",
            timestamp=now,
            actor_id=reviewer_id,
            details={
                "previous_version_hash": previous.version_hash,
                "resulting_version_hash": new_version.version_hash,
            },
        )
        return resolved

    @staticmethod
    def trivial_correction_blocker(case: EvidenceFeedbackCase) -> str | None:
        """Why ``case`` cannot take the deterministic trivial path, or ``None``.

        Only a lexicon typo/format defect triaged as auto-correctable and not
        routed to governed review qualifies; everything else stays with
        governed review.
        """

        if case.status is CaseStatus.GOVERNED_REVIEW_REQUIRED:
            return "GOVERNED_REVIEW_REQUIRED"
        if case.object_type_source == TYPE_SOURCE_MEMBER_CLAIMED:
            return "GOVERNED_REVIEW_REQUIRED"
        if case.disposition is not Disposition.AUTO_CORRECTABLE:
            return "GOVERNED_REVIEW_REQUIRED"
        if case.object_type is not ObjectType.LEXICON:
            return "SCIENTIFIC_OBJECT_CANNOT_AUTO_CORRECT"
        if case.defect_kind not in {"typo", "format"}:
            return "DEFECT_CLASS_NOT_AUTO_CORRECTABLE"
        return None

    def status_for_submitter(
        self,
        *,
        case_id: str,
        submitter_id: str,
    ) -> dict[str, Any]:
        case = self.repository.get_case(case_id)
        if case.submitter_id is None or case.submitter_id != submitter_id:
            raise PermissionError("CASE_STATUS_NOT_VISIBLE")
        return {
            "case_id": case.case_id,
            "status": case.status.value,
            "disposition": case.disposition.value,
            "resolution": case.resolution,
            "resulting_version_hash": case.resulting_version_hash,
        }

    @staticmethod
    def _triage(
        *,
        object_type: ObjectType,
        feedback_class: FeedbackClass,
        proposed_replacement: str | None,
        source_partner_id: str | None,
        defect_kind: str | None,
    ) -> tuple[Disposition, ReviewLane]:
        if source_partner_id:
            return (
                Disposition.NEEDS_SOURCE_PARTNER_REVIEW,
                ReviewLane.SOURCE_PARTNER,
            )
        if object_type is ObjectType.TAXONOMY:
            return Disposition.NEEDS_TAXONOMIC_REVIEW, ReviewLane.TAXONOMIC
        if object_type is ObjectType.IMAGE_ANNOTATION:
            return Disposition.NEEDS_SCIENTIFIC_REVIEW, ReviewLane.SCIENTIFIC
        if object_type in {
            ObjectType.MATRIX_IDENTIFICATION,
            ObjectType.LITERATURE_CLAIM,
            ObjectType.STRUCTURED_CHARACTER,
            ObjectType.DISTRIBUTION_RECORD,
        }:
            return Disposition.NEEDS_SCIENTIFIC_REVIEW, ReviewLane.SCIENTIFIC
        if (
            object_type is ObjectType.LEXICON
            and feedback_class is FeedbackClass.SUGGEST_CORRECTION
            and defect_kind in {"typo", "format"}
            and proposed_replacement
        ):
            return Disposition.AUTO_CORRECTABLE, ReviewLane.DETERMINISTIC
        return Disposition.INSUFFICIENT_EVIDENCE, ReviewLane.SCIENTIFIC
