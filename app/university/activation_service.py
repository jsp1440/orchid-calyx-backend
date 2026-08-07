from __future__ import annotations

from typing import Any

from app.mission_control_access import AccessPrincipal, Capability, CapabilityService

from .durable_config import durable_sessions_enabled
from .durable_repository import (
    DurableUniversityError,
    append_event as durable_append_event,
    create_session as durable_create_session,
    get_session as durable_get_session,
    record_review as durable_record_review,
    submit_session as durable_submit_session,
)
from .schemas import (
    InvestigationEventCreate,
    LabSession,
    SessionCreate,
    SessionReviewCreate,
    SessionSubmit,
)
from .service import UniversityServiceError, UniversitySessionService


_DURABLE_ERROR_STATUS = {
    "DURABLE_UNIVERSITY_DISABLED": 403,
    "DATABASE_URL_REQUIRED": 503,
    "DATABASE_SCHEMA_NOT_READY": 503,
    "SESSION_NOT_FOUND": 404,
    "SESSION_FORBIDDEN": 403,
    "SESSION_LOCKED": 409,
    "REVISION_REQUIRED": 422,
    "REVISION_CONFLICT": 409,
    "INVALID_STAGE_TRANSITION": 409,
    "INVALID_EVENT_TYPE": 422,
    "EVENT_STAGE_MISMATCH": 409,
    "STAGE_EXIT_REQUIREMENTS_UNMET": 409,
    "SUBMISSION_ENDPOINT_REQUIRED": 409,
    "SUBMISSION_NOT_READY": 409,
    "CHANGES_NOT_ADDRESSED": 409,
    "INVALID_REVIEW_STATE": 409,
    "REVIEW_CREATE_FAILED": 500,
    "SESSION_CREATE_FAILED": 500,
}
_REVIEW_CAPABILITIES = CapabilityService()
_SCIENTIFIC_REVIEW_QUALIFICATIONS = frozenset(
    {
        "qualified.science-reviewer",
        "qualified.expert-reviewer",
        "qualified.publication-reviewer",
    }
)


def _translate(exc: DurableUniversityError) -> UniversityServiceError:
    return UniversityServiceError(
        exc.code,
        _DURABLE_ERROR_STATUS.get(exc.code, 500),
        exc.message,
    )


def _event_to_api(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event["event_id"]),
        "event_type": event["event_type"],
        "stage": event["stage"],
        "payload": event.get("payload") or {},
        "actor": event["actor"],
        "session_revision": int(event["session_revision"]),
        "created_at": event["created_at"],
    }


def _session_to_api(row: dict[str, Any]) -> LabSession:
    return LabSession(
        session_id=str(row["session_id"]),
        laboratory_id=row["laboratory_id"],
        chapter_id=row["chapter_id"],
        actor=row["learner_actor"],
        status=row["status"],
        current_stage=row["current_stage"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revision=int(row["revision"]),
        events=[_event_to_api(event) for event in row.get("events", [])],
    )


def _required_review_capability(decision: str) -> str:
    if decision == "approved_for_candidate_knowledge_consideration":
        return Capability.REVIEW_EXPERT.value
    return Capability.REVIEW_SCIENCE.value


def qualified_reviewer_context(
    principal: AccessPrincipal,
    decision: str,
) -> dict[str, object]:
    """Return auditable reviewer authorization or fail closed."""
    required_capability = _required_review_capability(decision)
    scientific_qualifications = tuple(
        qualification
        for qualification in principal.qualifications
        if qualification in _SCIENTIFIC_REVIEW_QUALIFICATIONS
    )
    capability_decision = _REVIEW_CAPABILITIES.evaluate(principal, required_capability)
    if not scientific_qualifications or not capability_decision.allowed:
        raise UniversityServiceError(
            "REVIEWER_QUALIFICATION_REQUIRED",
            403,
            f"University review decision requires qualified capability {required_capability}",
        )
    return {
        "principal_id": principal.principal_id,
        "capability": required_capability,
        "roles": tuple(role.value for role in principal.roles),
        "qualifications": scientific_qualifications,
    }


class UniversityActivationService:
    """Dispatch session operations without weakening the verified-release gate."""

    @staticmethod
    def persistence_mode() -> str:
        return "postgres_durable" if durable_sessions_enabled() else "process_local_memory"

    @classmethod
    def create_session(cls, actor: str, payload: SessionCreate) -> LabSession:
        if not durable_sessions_enabled():
            return UniversitySessionService.create_session(actor, payload)
        UniversitySessionService.get_chapter(payload.chapter_id)
        UniversitySessionService.get_laboratory(payload.laboratory_id)
        if not any(
            link["laboratory_id"] == payload.laboratory_id
            for link in UniversitySessionService.get_chapter(payload.chapter_id)["laboratory_links"]
        ):
            raise UniversityServiceError(
                "CHAPTER_LAB_MISMATCH", 422, "Chapter does not launch this laboratory"
            )
        try:
            row = durable_create_session(
                laboratory_id=payload.laboratory_id,
                chapter_id=payload.chapter_id,
                learner_actor=actor,
            )
            row["events"] = []
            return _session_to_api(row)
        except DurableUniversityError as exc:
            raise _translate(exc) from exc

    @classmethod
    def get_session(cls, session_id: str, actor: str, privileged: bool) -> LabSession:
        if not durable_sessions_enabled():
            return UniversitySessionService.get_session(session_id, actor, privileged)
        try:
            return _session_to_api(
                durable_get_session(session_id=session_id, actor=actor, privileged=privileged)
            )
        except DurableUniversityError as exc:
            raise _translate(exc) from exc

    @classmethod
    def append_event(
        cls,
        session_id: str,
        actor: str,
        privileged: bool,
        payload: InvestigationEventCreate,
    ) -> LabSession:
        if not durable_sessions_enabled():
            return UniversitySessionService.append_event(session_id, actor, privileged, payload)
        if privileged:
            raise UniversityServiceError(
                "LEARNER_EVENT_ACTOR_REQUIRED",
                403,
                "Privileged reviewers may inspect durable sessions but may not author learner events",
            )
        if payload.expected_revision is None:
            raise UniversityServiceError(
                "REVISION_REQUIRED", 422, "expected_revision is required for durable session mutations"
            )
        try:
            durable_append_event(
                session_id=session_id,
                actor=actor,
                expected_revision=payload.expected_revision,
                event_type=payload.event_type,
                stage=payload.stage,
                payload=payload.payload,
            )
            return _session_to_api(
                durable_get_session(session_id=session_id, actor=actor, privileged=False)
            )
        except DurableUniversityError as exc:
            raise _translate(exc) from exc

    @classmethod
    def submit_session(cls, session_id: str, actor: str, payload: SessionSubmit) -> LabSession:
        if not durable_sessions_enabled():
            raise UniversityServiceError(
                "DURABLE_UNIVERSITY_REQUIRED",
                403,
                "Submission is available only after verified durable-session activation",
            )
        try:
            durable_submit_session(
                session_id=session_id,
                actor=actor,
                expected_revision=payload.expected_revision,
            )
            return _session_to_api(
                durable_get_session(session_id=session_id, actor=actor, privileged=False)
            )
        except DurableUniversityError as exc:
            raise _translate(exc) from exc

    @classmethod
    def review_session(
        cls,
        session_id: str,
        reviewer_principal: AccessPrincipal,
        payload: SessionReviewCreate,
    ) -> dict[str, Any]:
        if not durable_sessions_enabled():
            raise UniversityServiceError(
                "DURABLE_UNIVERSITY_REQUIRED",
                403,
                "Human review is available only after verified durable-session activation",
            )
        reviewer = qualified_reviewer_context(reviewer_principal, payload.decision)
        try:
            review = durable_record_review(
                session_id=session_id,
                reviewer_actor=str(reviewer["principal_id"]),
                reviewer_capability=str(reviewer["capability"]),
                reviewer_roles=tuple(reviewer["roles"]),
                reviewer_qualifications=tuple(reviewer["qualifications"]),
                reviewed_revision=payload.reviewed_revision,
                decision=payload.decision,
                notes=payload.notes,
            )
            return {
                "review_id": str(review["review_id"]),
                "session_id": str(review["session_id"]),
                "reviewer_actor": review["reviewer_actor"],
                "reviewer_capability": review["reviewer_capability"],
                "reviewer_roles": review.get("reviewer_roles") or [],
                "reviewer_qualifications": review.get("reviewer_qualifications") or [],
                "decision": review["decision"],
                "notes": review.get("notes"),
                "reviewed_revision": int(review["reviewed_revision"]),
                "candidate_knowledge_promoted": False,
                "publication_performed": False,
                "created_at": review["created_at"],
            }
        except DurableUniversityError as exc:
            raise _translate(exc) from exc
