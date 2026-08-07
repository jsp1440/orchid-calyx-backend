from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.university.activation_service import UniversityActivationService
from app.university.schemas import InvestigationEventCreate, SessionCreate, SessionReviewCreate, SessionSubmit
from app.university.service import UniversityServiceError, UniversitySessionService

NOW = datetime.now(timezone.utc)
BASE_ROW = {
    "session_id": "11111111-1111-1111-1111-111111111111",
    "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
    "chapter_id": "BITB-CHAPTER-ORCHID-FLOWERING-001",
    "learner_actor": "learner-1",
    "status": "created",
    "current_stage": "observe",
    "revision": 1,
    "created_at": NOW,
    "updated_at": NOW,
    "events": [],
}


class UniversityActivationServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        UniversitySessionService.reset_for_tests()

    def test_closed_durable_gate_preserves_process_local_prototype(self) -> None:
        payload = SessionCreate(
            laboratory_id="OCU-LAB-FAILURE-TO-BLOOM-001",
            chapter_id="BITB-CHAPTER-ORCHID-FLOWERING-001",
        )
        with patch("app.university.activation_service.durable_sessions_enabled", return_value=False):
            session = UniversityActivationService.create_session("learner-1", payload)
        self.assertTrue(session.session_id.startswith("OCU-SESSION-"))
        self.assertEqual(UniversityActivationService.persistence_mode(), "process_local_memory")

    def test_durable_event_requires_expected_revision(self) -> None:
        payload = InvestigationEventCreate(
            event_type="observation_added",
            stage="observe",
            payload={"text": "leaf yellowing"},
        )
        with patch("app.university.activation_service.durable_sessions_enabled", return_value=True):
            with self.assertRaises(UniversityServiceError) as ctx:
                UniversityActivationService.append_event(
                    "11111111-1111-1111-1111-111111111111",
                    "learner-1",
                    False,
                    payload,
                )
        self.assertEqual(ctx.exception.code, "REVISION_REQUIRED")

    def test_privileged_actor_cannot_author_learner_event_in_durable_mode(self) -> None:
        payload = InvestigationEventCreate(
            event_type="observation_added",
            stage="observe",
            expected_revision=1,
        )
        with patch("app.university.activation_service.durable_sessions_enabled", return_value=True):
            with self.assertRaises(UniversityServiceError) as ctx:
                UniversityActivationService.append_event("x", "operator", True, payload)
        self.assertEqual(ctx.exception.code, "LEARNER_EVENT_ACTOR_REQUIRED")

    def test_durable_create_maps_postgres_row_to_api_contract(self) -> None:
        payload = SessionCreate(
            laboratory_id="OCU-LAB-FAILURE-TO-BLOOM-001",
            chapter_id="BITB-CHAPTER-ORCHID-FLOWERING-001",
        )
        with patch("app.university.activation_service.durable_sessions_enabled", return_value=True), patch(
            "app.university.activation_service.durable_create_session", return_value=dict(BASE_ROW)
        ):
            session = UniversityActivationService.create_session("learner-1", payload)
        self.assertEqual(session.session_id, BASE_ROW["session_id"])
        self.assertEqual(session.actor, "learner-1")
        self.assertFalse(session.publication_allowed)
        self.assertFalse(session.automatic_candidate_knowledge)

    def test_submit_is_blocked_until_durable_gate_opens(self) -> None:
        with patch("app.university.activation_service.durable_sessions_enabled", return_value=False):
            with self.assertRaises(UniversityServiceError) as ctx:
                UniversityActivationService.submit_session("x", "learner-1", SessionSubmit(expected_revision=2))
        self.assertEqual(ctx.exception.code, "DURABLE_UNIVERSITY_REQUIRED")

    def test_review_requires_privileged_actor(self) -> None:
        payload = SessionReviewCreate(reviewed_revision=3, decision="approved_for_learning")
        with patch("app.university.activation_service.durable_sessions_enabled", return_value=True):
            with self.assertRaises(UniversityServiceError) as ctx:
                UniversityActivationService.review_session("x", "learner-1", False, payload)
        self.assertEqual(ctx.exception.code, "REVIEWER_PRIVILEGE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
