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
from .repository import EvidenceFeedbackRepository

Clock = Callable[[], str]


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
    ) -> EvidenceObjectVersion:
        now = self.clock()
        version = EvidenceObjectVersion(
            object_id=object_id.strip(),
            object_type=object_type,
            version_hash=content_hash(payload),
            payload=payload,
            created_at=now,
            previous_version_hash=previous_version_hash,
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
    ) -> SubmissionResult:
        if not statement.strip():
            raise ValueError("FEEDBACK_STATEMENT_REQUIRED")
        persisted = self.repository.get_object_version(
            object_id,
            object_version_hash,
        )
        if persisted.object_type is not object_type:
            raise ValueError("OBJECT_TYPE_MISMATCH")

        fingerprint = feedback_fingerprint(
            object_id=object_id,
            object_version_hash=object_version_hash,
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
        # Serialized per case so two reviewers cannot both resolve it.
        return self.repository.atomic(
            lambda: self._accept_trivial_correction(
                case_id=case_id,
                reviewer_id=reviewer_id,
                corrected_payload=corrected_payload,
            ),
            lock_key=f"case:{case_id.strip()}",
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
