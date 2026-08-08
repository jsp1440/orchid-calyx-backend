"""Bounded Orchid Continuum University foundation for CALYX issue #454.

University consumes candidate Knowledge Explorer concepts and private Research Station
projects. It provides deterministic learning workflows only: no real equipment control,
high-stakes credential grading, scientific publication, deployment, or Knowledge Graph writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.knowledge_explorer import KnowledgeExplorerService
from runtime.research_station import ResearchStationService

UNIVERSITY_SCHEMA_VERSION = "calyx-university/v1"
LAB_STATES = {"not_started", "observe", "hypothesize", "simulate", "reflect", "complete"}
LAB_TRANSITIONS = {
    "not_started": {"observe"},
    "observe": {"hypothesize"},
    "hypothesize": {"simulate", "observe"},
    "simulate": {"reflect", "hypothesize"},
    "reflect": {"complete", "simulate"},
    "complete": set(),
}
QUESTION_TYPES = {"multiple_choice", "multiple_select", "short_response"}


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def university_root() -> Path:
    return Path(os.getenv("CALYX_UNIVERSITY_DIR", "/tmp/calyx/university"))


@dataclass(frozen=True)
class Objective:
    objective_id: str
    text: str
    measurable_action: str


@dataclass(frozen=True)
class Activity:
    activity_id: str
    title: str
    instructions: str
    activity_type: str
    concept_ids: tuple[str, ...]


@dataclass(frozen=True)
class RubricCriterion:
    criterion_id: str
    description: str
    max_points: int


class UniversityService:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        knowledge: KnowledgeExplorerService | None = None,
        research: ResearchStationService | None = None,
    ) -> None:
        self.workspace = workspace or university_root()
        self.knowledge = knowledge or KnowledgeExplorerService()
        self.research = research or ResearchStationService()

    @staticmethod
    def _owner_key(owner_id: str) -> str:
        owner = _text(owner_id)
        if not owner:
            raise ValueError("UNIVERSITY_OWNER_REQUIRED")
        return _sha(owner.casefold())[:24]

    def _root(self, owner_id: str) -> Path:
        return self.workspace / "owners" / self._owner_key(owner_id)

    @staticmethod
    def _safe(value: str, field: str) -> str:
        clean = _text(value)
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError(f"UNIVERSITY_{field.upper()}_INVALID")
        return clean

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def _path(self, owner_id: str, kind: str, record_id: str) -> Path:
        return self._root(owner_id) / kind / f"{self._safe(record_id, kind)}.json"

    def create_course(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = self._safe(payload.get("course_id"), "course_id")
        title = _text(payload.get("title"))
        description = _text(payload.get("description"))
        audience = _text(payload.get("audience"))
        if not title or not description or not audience:
            raise ValueError("UNIVERSITY_COURSE_FIELDS_REQUIRED")
        record = {
            "schema_version": UNIVERSITY_SCHEMA_VERSION,
            "course_id": course_id,
            "title": title,
            "description": description,
            "audience": audience,
            "prerequisite_course_ids": sorted({_text(v) for v in payload.get("prerequisite_course_ids", []) if _text(v)}),
            "accessible_learner_payload_required": True,
            "instructor_payload_required": True,
            "scientific_publication_authorized": False,
        }
        path = self._path(owner_id, "courses", course_id)
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("UNIVERSITY_COURSE_IMMUTABLE_CONFLICT")
            return {"created": False, "course": existing}
        _atomic(path, record)
        return {"created": True, "course": record}

    def create_lesson(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = self._safe(payload.get("course_id"), "course_id")
        self._read(self._path(owner_id, "courses", course_id))
        lesson_id = self._safe(payload.get("lesson_id"), "lesson_id")
        title = _text(payload.get("title"))
        summary = _text(payload.get("summary"))
        if not title or not summary:
            raise ValueError("UNIVERSITY_LESSON_FIELDS_REQUIRED")

        objectives: list[dict[str, Any]] = []
        for item in payload.get("objectives", []):
            objective = Objective(
                objective_id=self._safe(item.get("objective_id"), "objective_id"),
                text=_text(item.get("text")),
                measurable_action=_text(item.get("measurable_action")),
            )
            if not objective.text or not objective.measurable_action:
                raise ValueError("UNIVERSITY_OBJECTIVE_FIELDS_REQUIRED")
            objectives.append(asdict(objective))
        if not objectives:
            raise ValueError("UNIVERSITY_OBJECTIVE_REQUIRED")

        concept_ids = []
        evidence_links: list[dict[str, Any]] = []
        for item in payload.get("concept_coverage", []):
            concept_id = self._safe(item.get("concept_id"), "concept_id")
            concept = self.knowledge.get(concept_id)
            requested_evidence = sorted({_text(v) for v in item.get("evidence_ids", []) if _text(v)})
            known = {ev["evidence_id"] for ev in concept["evidence_spans"]}
            if not requested_evidence or not set(requested_evidence) <= known:
                raise ValueError("UNIVERSITY_CONCEPT_EVIDENCE_INVALID")
            concept_ids.append(concept_id)
            evidence_links.append(
                {
                    "concept_id": concept_id,
                    "preferred_term": concept["preferred_term"],
                    "evidence_ids": requested_evidence,
                    "candidate_only": concept["candidate_only"],
                    "scientific_review_required": concept["scientific_review_required"],
                }
            )
        if not concept_ids:
            raise ValueError("UNIVERSITY_CONCEPT_COVERAGE_REQUIRED")

        activities: list[dict[str, Any]] = []
        for item in payload.get("activities", []):
            activity = Activity(
                activity_id=self._safe(item.get("activity_id"), "activity_id"),
                title=_text(item.get("title")),
                instructions=_text(item.get("instructions")),
                activity_type=_text(item.get("activity_type")),
                concept_ids=tuple(_text(v) for v in item.get("concept_ids", []) if _text(v)),
            )
            if not activity.title or not activity.instructions or not activity.activity_type:
                raise ValueError("UNIVERSITY_ACTIVITY_FIELDS_REQUIRED")
            if not set(activity.concept_ids) <= set(concept_ids):
                raise ValueError("UNIVERSITY_ACTIVITY_CONCEPT_UNKNOWN")
            activities.append(asdict(activity))

        learner = dict(payload.get("learner_payload") or {})
        instructor = dict(payload.get("instructor_payload") or {})
        if not _text(learner.get("accessible_summary")) or not _text(learner.get("alt_format_note")):
            raise ValueError("UNIVERSITY_ACCESSIBLE_LEARNER_PAYLOAD_REQUIRED")
        if not _text(instructor.get("teaching_notes")) or not _text(instructor.get("review_note")):
            raise ValueError("UNIVERSITY_INSTRUCTOR_PAYLOAD_REQUIRED")

        record = {
            "schema_version": UNIVERSITY_SCHEMA_VERSION,
            "lesson_id": lesson_id,
            "course_id": course_id,
            "title": title,
            "summary": summary,
            "prerequisite_lesson_ids": sorted({_text(v) for v in payload.get("prerequisite_lesson_ids", []) if _text(v)}),
            "objectives": objectives,
            "concept_coverage": evidence_links,
            "activities": activities,
            "learner_payload": learner,
            "instructor_payload": instructor,
            "candidate_science_only": True,
            "scientific_review_required": True,
            "scientific_publication_authorized": False,
        }
        record["lesson_sha256"] = _sha(_stable(record))
        path = self._path(owner_id, "lessons", lesson_id)
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("UNIVERSITY_LESSON_IMMUTABLE_CONFLICT")
            return {"created": False, "lesson": existing}
        _atomic(path, record)
        return {"created": True, "lesson": record}

    def glossary(self, term: str, *, level: str = "learner") -> dict[str, Any]:
        result = self.knowledge.popover(term, level=level)
        return {
            "resolution": result,
            "candidate_science_only": True,
            "scientific_review_required": True,
            "scientific_publication_authorized": False,
        }

    def create_virtual_lab(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        lab_id = self._safe(payload.get("lab_id"), "lab_id")
        lesson_id = self._safe(payload.get("lesson_id"), "lesson_id")
        self._read(self._path(owner_id, "lessons", lesson_id))
        research_project_id = self._safe(payload.get("research_project_id"), "research_project_id")
        research_readiness = self.research.readiness(owner_id, research_project_id)
        scenario = _text(payload.get("scenario"))
        if not scenario:
            raise ValueError("UNIVERSITY_LAB_SCENARIO_REQUIRED")
        allowed_actions = sorted({_text(v) for v in payload.get("allowed_actions", []) if _text(v)})
        if not allowed_actions:
            raise ValueError("UNIVERSITY_LAB_ACTIONS_REQUIRED")
        forbidden = {"open_valve", "switch_heater", "dose_chemical", "control_equipment", "send_actuator_command"}
        if forbidden & {item.casefold() for item in allowed_actions}:
            raise ValueError("UNIVERSITY_REAL_EQUIPMENT_ACTION_FORBIDDEN")
        record = {
            "schema_version": UNIVERSITY_SCHEMA_VERSION,
            "lab_id": lab_id,
            "lesson_id": lesson_id,
            "research_project_id": research_project_id,
            "research_manifest_sha256": research_readiness["reproducibility_manifest_sha256"],
            "scenario": scenario,
            "allowed_actions": allowed_actions,
            "initial_state": "not_started",
            "state_machine": {state: sorted(targets) for state, targets in LAB_TRANSITIONS.items()},
            "simulated_only": True,
            "real_equipment_control": False,
        }
        path = self._path(owner_id, "virtual-labs", lab_id)
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("UNIVERSITY_LAB_IMMUTABLE_CONFLICT")
            return {"created": False, "lab": existing}
        _atomic(path, record)
        return {"created": True, "lab": record}

    def start_lab_session(self, owner_id: str, lab_id: str, learner_id: str, started_at: str) -> dict[str, Any]:
        lab = self._read(self._path(owner_id, "virtual-labs", lab_id))
        learner = _text(learner_id)
        started = _text(started_at)
        if not learner or not started:
            raise ValueError("UNIVERSITY_LAB_SESSION_FIELDS_REQUIRED")
        session_id = f"lab-session-{_sha(lab_id + ':' + learner + ':' + started)[:20]}"
        record = {
            "schema_version": UNIVERSITY_SCHEMA_VERSION,
            "session_id": session_id,
            "lab_id": lab_id,
            "lesson_id": lab["lesson_id"],
            "learner_id": learner,
            "state": "not_started",
            "history": [{"state": "not_started", "at": started, "action": "start"}],
            "simulated_only": True,
            "real_equipment_control": False,
        }
        path = self._path(owner_id, "lab-sessions", session_id)
        if path.exists():
            return {"created": False, "session": self._read(path)}
        _atomic(path, record)
        return {"created": True, "session": record}

    def transition_lab(self, owner_id: str, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._path(owner_id, "lab-sessions", session_id)
        session = self._read(path)
        target = _text(payload.get("target_state")).casefold()
        action = _text(payload.get("action"))
        at = _text(payload.get("at"))
        if target not in LAB_STATES or target not in LAB_TRANSITIONS[session["state"]]:
            raise ValueError("UNIVERSITY_LAB_TRANSITION_INVALID")
        if not action or not at:
            raise ValueError("UNIVERSITY_LAB_TRANSITION_FIELDS_REQUIRED")
        forbidden_actions = {"open_valve", "switch_heater", "dose_chemical", "control_equipment", "send_actuator_command"}
        if action.casefold() in forbidden_actions:
            raise ValueError("UNIVERSITY_REAL_EQUIPMENT_ACTION_FORBIDDEN")
        session["state"] = target
        session["history"].append({"state": target, "at": at, "action": action, "observation": _text(payload.get("observation")) or None})
        _atomic(path, session)
        return session

    def create_question_bank(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        bank_id = self._safe(payload.get("bank_id"), "bank_id")
        version = self._safe(payload.get("version"), "version")
        lesson_id = self._safe(payload.get("lesson_id"), "lesson_id")
        self._read(self._path(owner_id, "lessons", lesson_id))
        questions: list[dict[str, Any]] = []
        ids: set[str] = set()
        for item in payload.get("questions", []):
            question_id = self._safe(item.get("question_id"), "question_id")
            question_type = _text(item.get("question_type")).casefold()
            prompt = _text(item.get("prompt"))
            rationale = _text(item.get("answer_rationale"))
            if question_id in ids or question_type not in QUESTION_TYPES or not prompt or not rationale:
                raise ValueError("UNIVERSITY_QUESTION_INVALID")
            ids.add(question_id)
            options = list(item.get("options") or [])
            accepted_answers = list(item.get("accepted_answers") or [])
            if question_type in {"multiple_choice", "multiple_select"} and (not options or not accepted_answers):
                raise ValueError("UNIVERSITY_QUESTION_OPTIONS_REQUIRED")
            questions.append(
                {
                    "question_id": question_id,
                    "question_type": question_type,
                    "prompt": prompt,
                    "options": options,
                    "accepted_answers": accepted_answers,
                    "answer_rationale": rationale,
                    "objective_ids": sorted({_text(v) for v in item.get("objective_ids", []) if _text(v)}),
                }
            )
        if not questions:
            raise ValueError("UNIVERSITY_QUESTION_REQUIRED")
        rubric = []
        for item in payload.get("rubric", []):
            criterion = RubricCriterion(
                criterion_id=self._safe(item.get("criterion_id"), "criterion_id"),
                description=_text(item.get("description")),
                max_points=int(item.get("max_points", 0)),
            )
            if not criterion.description or criterion.max_points <= 0:
                raise ValueError("UNIVERSITY_RUBRIC_INVALID")
            rubric.append(asdict(criterion))
        if not rubric:
            raise ValueError("UNIVERSITY_RUBRIC_REQUIRED")
        record = {
            "schema_version": UNIVERSITY_SCHEMA_VERSION,
            "bank_id": bank_id,
            "version": version,
            "lesson_id": lesson_id,
            "questions": questions,
            "rubric": rubric,
            "high_stakes_credential": False,
            "autonomous_high_stakes_grading": False,
        }
        record["bank_sha256"] = _sha(_stable(record))
        key = f"{bank_id}-{version}"
        path = self._path(owner_id, "question-banks", key)
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("UNIVERSITY_QUESTION_BANK_IMMUTABLE_CONFLICT")
            return {"created": False, "question_bank": existing}
        _atomic(path, record)
        return {"created": True, "question_bank": record}

    def record_progress(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        learner_id = _text(payload.get("learner_id"))
        lesson_id = self._safe(payload.get("lesson_id"), "lesson_id")
        event_type = _text(payload.get("event_type")).casefold()
        at = _text(payload.get("at"))
        if not learner_id or event_type not in {"started", "activity_completed", "lab_completed", "assessment_submitted", "lesson_completed"} or not at:
            raise ValueError("UNIVERSITY_PROGRESS_EVENT_INVALID")
        self._read(self._path(owner_id, "lessons", lesson_id))
        material = _stable({"learner_id": learner_id, "lesson_id": lesson_id, "event_type": event_type, "at": at, "detail": payload.get("detail")})
        event_id = f"progress-{_sha(material)[:20]}"
        record = {
            "schema_version": UNIVERSITY_SCHEMA_VERSION,
            "event_id": event_id,
            "learner_id": learner_id,
            "lesson_id": lesson_id,
            "event_type": event_type,
            "at": at,
            "detail": dict(payload.get("detail") or {}),
            "credential_decision": False,
        }
        path = self._path(owner_id, "progress-events", event_id)
        if path.exists():
            return {"created": False, "progress_event": self._read(path)}
        _atomic(path, record)
        return {"created": True, "progress_event": record}

    def learner_lesson(self, owner_id: str, lesson_id: str) -> dict[str, Any]:
        lesson = self._read(self._path(owner_id, "lessons", lesson_id))
        concepts = [
            self.knowledge.popover(item["preferred_term"], level="learner")
            for item in lesson["concept_coverage"]
        ]
        return {
            "lesson_id": lesson_id,
            "title": lesson["title"],
            "summary": lesson["summary"],
            "objectives": lesson["objectives"],
            "activities": lesson["activities"],
            "learner_payload": lesson["learner_payload"],
            "glossary": concepts,
            "accessible": True,
            "candidate_science_only": True,
            "scientific_review_required": True,
        }

    def instructor_lesson(self, owner_id: str, lesson_id: str) -> dict[str, Any]:
        lesson = self._read(self._path(owner_id, "lessons", lesson_id))
        return {
            **lesson,
            "instructor_payload": lesson["instructor_payload"],
            "high_stakes_credential_authority": False,
            "autonomous_high_stakes_grading": False,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        root = self._root(owner_id)

        def count(kind: str) -> int:
            directory = root / kind
            return len(list(directory.glob("*.json"))) if directory.exists() else 0

        return {
            "schema_version": UNIVERSITY_SCHEMA_VERSION,
            "courses": count("courses"),
            "lessons": count("lessons"),
            "virtual_labs": count("virtual-labs"),
            "lab_sessions": count("lab-sessions"),
            "question_banks": count("question-banks"),
            "progress_events": count("progress-events"),
            "knowledge_explorer": self.knowledge.readiness(),
            "simulated_lab_only": True,
            "real_equipment_control": False,
            "autonomous_high_stakes_grading": False,
            "scientific_publication_authorized": False,
            "production_deployment_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "decision": "UNIVERSITY_REVIEW_READY",
        }
