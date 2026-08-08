"""Protected Orchid Continuum University routes for CALYX issue #454."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.university_operational import UniversityService

router = APIRouter(prefix="/brain/mission-control/university", tags=["mission-control-university"])
_service_instance = UniversityService()


def _service() -> UniversityService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail="university owner scope unavailable")
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


class CourseRequest(BaseModel):
    course_id: str
    title: str
    description: str
    audience: str
    prerequisite_course_ids: list[str] = Field(default_factory=list, max_length=100)


class LessonRequest(BaseModel):
    lesson_id: str
    course_id: str
    title: str
    summary: str
    prerequisite_lesson_ids: list[str] = Field(default_factory=list, max_length=100)
    objectives: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    concept_coverage: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    activities: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    learner_payload: dict[str, Any]
    instructor_payload: dict[str, Any]


class VirtualLabRequest(BaseModel):
    lab_id: str
    lesson_id: str
    research_project_id: str
    scenario: str
    allowed_actions: list[str] = Field(min_length=1, max_length=100)


class StartLabRequest(BaseModel):
    learner_id: str
    started_at: str


class LabTransitionRequest(BaseModel):
    target_state: str
    action: str
    at: str
    observation: str | None = None


class QuestionBankRequest(BaseModel):
    bank_id: str
    version: str
    lesson_id: str
    questions: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    rubric: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class ProgressRequest(BaseModel):
    learner_id: str
    lesson_id: str
    event_type: str
    at: str
    detail: dict[str, Any] = Field(default_factory=dict)


@router.post("/courses")
def create_course(request: CourseRequest, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().create_course(_owner(identity), request.model_dump())
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/lessons")
def create_lesson(request: LessonRequest, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().create_lesson(_owner(identity), request.model_dump())
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/glossary/{term}")
def glossary(term: str, level: str = Query("learner"), identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    _owner(identity)
    try:
        return _service().glossary(term, level=level)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/virtual-labs")
def create_virtual_lab(request: VirtualLabRequest, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().create_virtual_lab(_owner(identity), request.model_dump())
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/virtual-labs/{lab_id}/sessions")
def start_lab(lab_id: str, request: StartLabRequest, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().start_lab_session(_owner(identity), lab_id, request.learner_id, request.started_at)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/lab-sessions/{session_id}/transitions")
def transition_lab(session_id: str, request: LabTransitionRequest, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().transition_lab(_owner(identity), session_id, request.model_dump())
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/question-banks")
def create_question_bank(request: QuestionBankRequest, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().create_question_bank(_owner(identity), request.model_dump())
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/progress")
def record_progress(request: ProgressRequest, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().record_progress(_owner(identity), request.model_dump())
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/lessons/{lesson_id}/learner")
def learner_lesson(lesson_id: str, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().learner_lesson(_owner(identity), lesson_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/lessons/{lesson_id}/instructor")
def instructor_lesson(lesson_id: str, identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    try:
        return _service().instructor_lesson(_owner(identity), lesson_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/readiness")
def readiness(identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    return _service().readiness(_owner(identity))
