from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import university_operational as api
from app.security import verify_owner_or_api_key
from runtime.knowledge_explorer import KnowledgeExplorerService
from runtime.research_station import ResearchStationService
from runtime.university_operational import UniversityService

OWNER = "university-owner"


def _knowledge(root: Path) -> KnowledgeExplorerService:
    service = KnowledgeExplorerService(root / "knowledge")
    service.register_candidate({
        "concept_id": "velamen",
        "preferred_term": "velamen",
        "synonyms": ["velamen radicum"],
        "definitions": {
            "plain": "A multilayered root covering found on many epiphytic orchids.",
            "learner": "Velamen is a specialized outer root tissue that rapidly interacts with water and the aerial environment.",
            "advanced": "Velamen is a multilayered dead-at-maturity epidermal derivative of many orchid roots with structural and ecological functions.",
        },
        "evidence_spans": [{
            "evidence_id": "ev-velamen-1",
            "source_uri": "fixture://university/velamen",
            "source_title": "University fixture evidence",
            "text": "Velamen forms a multilayered outer covering on many orchid roots.",
            "locator": {"section": "fixture"},
        }],
        "images": [],
        "figures": [],
        "relationships": [],
    })
    return service


def _service(tmp_path: Path) -> UniversityService:
    research = ResearchStationService(tmp_path / "research")
    research.create_project(OWNER, {
        "project_id": "velamen-observation",
        "title": "Velamen observation",
        "objective": "Provide a reproducible simulated observation context.",
        "state": "active",
        "created_at": "2026-08-07T22:00:00-07:00",
    })
    return UniversityService(tmp_path / "university", knowledge=_knowledge(tmp_path), research=research)


def _lesson(service: UniversityService) -> None:
    service.create_course(OWNER, {
        "course_id": "orchid-roots-101",
        "title": "Orchid Roots 101",
        "description": "Evidence-linked introduction to orchid root biology.",
        "audience": "adult learner",
    })
    service.create_lesson(OWNER, {
        "lesson_id": "velamen-foundations",
        "course_id": "orchid-roots-101",
        "title": "Velamen Foundations",
        "summary": "Observe, define, and reason about velamen without treating candidate science as published fact.",
        "objectives": [{"objective_id": "obj-1", "text": "Explain velamen structure.", "measurable_action": "Describe two structural features."}],
        "concept_coverage": [{"concept_id": "velamen", "evidence_ids": ["ev-velamen-1"]}],
        "activities": [{"activity_id": "act-1", "title": "Evidence check", "instructions": "Compare the definition with its evidence span.", "activity_type": "review", "concept_ids": ["velamen"]}],
        "learner_payload": {"accessible_summary": "A text-first lesson with glossary support.", "alt_format_note": "All essential content is available as text."},
        "instructor_payload": {"teaching_notes": "Emphasize evidence provenance.", "review_note": "Scientific content remains review-required."},
    })


def test_lesson_glossary_and_accessible_payloads(tmp_path: Path):
    service = _service(tmp_path)
    _lesson(service)
    learner = service.learner_lesson(OWNER, "velamen-foundations")
    instructor = service.instructor_lesson(OWNER, "velamen-foundations")
    assert learner["accessible"] is True
    assert learner["glossary"][0]["resolution"]["state"] == "matched"
    assert instructor["autonomous_high_stakes_grading"] is False


def test_virtual_lab_is_deterministic_and_cannot_control_equipment(tmp_path: Path):
    service = _service(tmp_path)
    _lesson(service)
    lab = service.create_virtual_lab(OWNER, {
        "lab_id": "velamen-water-lab",
        "lesson_id": "velamen-foundations",
        "research_project_id": "velamen-observation",
        "scenario": "Simulate observations of water contacting orchid root surfaces.",
        "allowed_actions": ["record_observation", "compare_images"],
    })["lab"]
    assert lab["simulated_only"] is True
    session = service.start_lab_session(OWNER, lab["lab_id"], "learner-1", "2026-08-07T22:10:00-07:00")["session"]
    state = service.transition_lab(OWNER, session["session_id"], {"target_state": "observe", "action": "record_observation", "at": "2026-08-07T22:11:00-07:00"})
    assert state["state"] == "observe"
    with pytest.raises(ValueError, match="REAL_EQUIPMENT"):
        service.transition_lab(OWNER, session["session_id"], {"target_state": "hypothesize", "action": "open_valve", "at": "2026-08-07T22:12:00-07:00"})


def test_versioned_assessment_has_rationale_rubric_and_no_high_stakes_authority(tmp_path: Path):
    service = _service(tmp_path)
    _lesson(service)
    bank = service.create_question_bank(OWNER, {
        "bank_id": "velamen-check",
        "version": "1.0",
        "lesson_id": "velamen-foundations",
        "questions": [{"question_id": "q1", "question_type": "multiple_choice", "prompt": "Which tissue is the lesson about?", "options": ["velamen", "pollen"], "accepted_answers": ["velamen"], "answer_rationale": "The lesson evidence explicitly concerns velamen.", "objective_ids": ["obj-1"]}],
        "rubric": [{"criterion_id": "r1", "description": "Uses evidence-linked terminology.", "max_points": 2}],
    })["question_bank"]
    assert bank["version"] == "1.0"
    assert bank["questions"][0]["answer_rationale"]
    assert bank["autonomous_high_stakes_grading"] is False


def test_progress_and_readiness_preserve_governance(tmp_path: Path):
    service = _service(tmp_path)
    _lesson(service)
    service.record_progress(OWNER, {"learner_id": "learner-1", "lesson_id": "velamen-foundations", "event_type": "started", "at": "2026-08-07T22:20:00-07:00"})
    ready = service.readiness(OWNER)
    assert ready["courses"] == 1 and ready["lessons"] == 1 and ready["progress_events"] == 1
    assert ready["real_equipment_control"] is False
    assert ready["scientific_publication_authorized"] is False
    assert ready["knowledge_graph_mutation_authorized"] is False


def test_protected_api_surface(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)
    response = client.post("/brain/mission-control/university/courses", json={"course_id": "api-course", "title": "API Course", "description": "Protected route test.", "audience": "tester", "prerequisite_course_ids": []})
    assert response.status_code == 200
    readiness = client.get("/brain/mission-control/university/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["autonomous_high_stakes_grading"] is False
