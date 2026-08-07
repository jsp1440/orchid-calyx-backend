from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.university.activation_service import UniversityActivationService, qualified_reviewer_context
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


def administrator_principal() -> AccessPrincipal:
    return AccessPrincipal(
        principal_id="backend_api_key",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=True,
    )


def science_reviewer_principal() -> AccessPrincipal:
    return AccessPrincipal(
        principal_id="reviewer-science",
        roles=(MissionControlRole.VOLUNTEER,),
        qualifications=("qualified.science-reviewer",),
        authenticated=True,
    )


def expert_reviewer_principal() -> AccessPrincipal:
    return AccessPrincipal(
        principal_id="reviewer-expert",
        roles=(MissionControlRole.EXPERT,),
        qualifications=("qualified.expert-reviewer",),
        authenticated=True,
    )


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

    def test_generic_administrator_cannot_make_scientific_review_decision(self) -> None:
        with self.assertRaises(UniversityServiceError) as ctx:
            qualified_reviewer_context(administrator_principal(), "approved_for_learning")
        self.assertEqual(ctx.exception.code, "REVIEWER_QUALIFICATION_REQUIRED")

    def test_qualified_science_reviewer_can_make_learning_decision(self) -> None:
        context = qualified_reviewer_context(science_reviewer_principal(), "approved_for_learning")
        self.assertEqual(context["principal_id"], "reviewer-science")
        self.assertEqual(context["capability"], "review.science")
        self.assertEqual(context["qualifications"], ("qualified.science-reviewer",))

    def test_candidate_knowledge_consideration_requires_expert_review(self) -> None:
        with self.assertRaises(UniversityServiceError) as ctx:
            qualified_reviewer_context(
                science_reviewer_principal(),
                "approved_for_candidate_knowledge_consideration",
            )
        self.assertEqual(ctx.exception.code, "REVIEWER_QUALIFICATION_REQUIRED")
        context = qualified_reviewer_context(
            expert_reviewer_principal(),
            "approved_for_candidate_knowledge_consideration",
        )
        self.assertEqual(context["capability"], "review.expert")
        self.assertEqual(context["qualifications"], ("qualified.expert-reviewer",))

    def test_durable_review_persists_reviewer_authorization_provenance(self) -> None:
        payload = SessionReviewCreate(reviewed_revision=3, decision="approved_for_learning")
        review_row = {
            "review_id": "22222222-2222-2222-2222-222222222222",
            "session_id": BASE_ROW["session_id"],
            "reviewer_actor": "reviewer-science",
            "reviewer_capability": "review.science",
            "reviewer_roles": ["VOLUNTEER"],
            "reviewer_qualifications": ["qualified.science-reviewer"],
            "decision": "approved_for_learning",
            "notes": None,
            "reviewed_revision": 3,
            "created_at": NOW,
        }
        with patch("app.university.activation_service.durable_sessions_enabled", return_value=True), patch(
            "app.university.activation_service.durable_record_review", return_value=review_row
        ) as record_review:
            result = UniversityActivationService.review_session(
                BASE_ROW["session_id"], science_reviewer_principal(), payload
            )
        record_review.assert_called_once_with(
            session_id=BASE_ROW["session_id"],
            reviewer_actor="reviewer-science",
            reviewer_capability="review.science",
            reviewer_roles=("VOLUNTEER",),
            reviewer_qualifications=("qualified.science-reviewer",),
            reviewed_revision=3,
            decision="approved_for_learning",
            notes=None,
        )
        self.assertEqual(result["reviewer_capability"], "review.science")
        self.assertFalse(result["candidate_knowledge_promoted"])
        self.assertFalse(result["publication_performed"])


if __name__ == "__main__":
    unittest.main()
