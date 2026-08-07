from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from .fixtures import CHAPTER, LABORATORY
from .schemas import InvestigationEventCreate, LabSession, SessionCreate, SessionEvent

_STAGE_STATUS = {
    "observe": "observing",
    "question": "questioning",
    "investigate": "investigating",
    "analyze": "analyzing",
    "interpret": "interpreting",
    "communicate": "communicating",
    "contribute": "submitted",
}
_STAGE_INDEX = {stage: index for index, stage in enumerate(LABORATORY["inquiry_sequence"])}


class UniversityServiceError(ValueError):
    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class UniversitySessionService:
    """Process-local prototype store.

    This intentionally avoids database writes in OCU-SCI-003. Sessions disappear on
    process restart and must not be represented as durable learner records.
    """

    _sessions: dict[str, LabSession] = {}
    _lock = RLock()

    @staticmethod
    def catalog() -> tuple[dict, dict]:
        return CHAPTER, LABORATORY

    @staticmethod
    def get_chapter(chapter_id: str) -> dict:
        if chapter_id != CHAPTER["chapter_id"]:
            raise UniversityServiceError("CHAPTER_NOT_FOUND", 404, "Chapter not found")
        return CHAPTER

    @staticmethod
    def get_laboratory(laboratory_id: str) -> dict:
        if laboratory_id != LABORATORY["laboratory_id"]:
            raise UniversityServiceError("LABORATORY_NOT_FOUND", 404, "Laboratory not found")
        return LABORATORY

    @classmethod
    def create_session(cls, actor: str, payload: SessionCreate) -> LabSession:
        cls.get_chapter(payload.chapter_id)
        cls.get_laboratory(payload.laboratory_id)
        if not any(
            link["laboratory_id"] == payload.laboratory_id
            for link in CHAPTER["laboratory_links"]
        ):
            raise UniversityServiceError(
                "CHAPTER_LAB_MISMATCH", 422, "Chapter does not launch this laboratory"
            )
        now = datetime.now(timezone.utc)
        session = LabSession(
            session_id=f"OCU-SESSION-{uuid4()}",
            laboratory_id=payload.laboratory_id,
            chapter_id=payload.chapter_id,
            actor=actor,
            status="created",
            current_stage="observe",
            created_at=now,
            updated_at=now,
        )
        with cls._lock:
            cls._sessions[session.session_id] = session
        return session.model_copy(deep=True)

    @classmethod
    def get_session(cls, session_id: str, actor: str, privileged: bool) -> LabSession:
        with cls._lock:
            session = cls._sessions.get(session_id)
            if session is None:
                raise UniversityServiceError("SESSION_NOT_FOUND", 404, "Session not found")
            if not privileged and session.actor != actor:
                raise UniversityServiceError("SESSION_FORBIDDEN", 403, "Session is not owned by actor")
            return session.model_copy(deep=True)

    @classmethod
    def append_event(
        cls,
        session_id: str,
        actor: str,
        privileged: bool,
        payload: InvestigationEventCreate,
    ) -> LabSession:
        with cls._lock:
            session = cls._sessions.get(session_id)
            if session is None:
                raise UniversityServiceError("SESSION_NOT_FOUND", 404, "Session not found")
            if not privileged and session.actor != actor:
                raise UniversityServiceError("SESSION_FORBIDDEN", 403, "Session is not owned by actor")
            if session.status in {"submitted", "under_review", "approved_for_learning", "archived"}:
                raise UniversityServiceError("SESSION_LOCKED", 409, "Session no longer accepts learner events")
            current_index = _STAGE_INDEX[session.current_stage]
            requested_index = _STAGE_INDEX[payload.stage]
            if requested_index < current_index or requested_index > current_index + 1:
                raise UniversityServiceError(
                    "INVALID_STAGE_TRANSITION",
                    409,
                    "Events may remain in the current stage or advance exactly one stage",
                )
            next_revision = session.revision + 1
            event = SessionEvent(
                event_id=f"OCU-EVENT-{uuid4()}",
                event_type=payload.event_type,
                stage=payload.stage,
                payload=payload.payload,
                actor=actor,
                session_revision=next_revision,
                created_at=datetime.now(timezone.utc),
            )
            session.events.append(event)
            session.current_stage = payload.stage
            session.status = _STAGE_STATUS[payload.stage]
            session.updated_at = event.created_at
            session.revision = next_revision
            cls._sessions[session_id] = session
            return session.model_copy(deep=True)

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._sessions.clear()
