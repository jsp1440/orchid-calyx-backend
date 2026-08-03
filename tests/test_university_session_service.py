from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.university.config import session_writes_enabled, university_enabled
from app.university.schemas import InvestigationEventCreate, SessionCreate
from app.university.service import UniversityServiceError, UniversitySessionService


class UniversityFeatureFlagTests(unittest.TestCase):
    def test_university_is_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(university_enabled())
            self.assertFalse(session_writes_enabled())

    def test_session_writes_require_both_flags(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OCU_UNIVERSITY_ENABLED": "true",
                "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            },
            clear=True,
        ):
            self.assertTrue(university_enabled())
            self.assertTrue(session_writes_enabled())


class UniversitySessionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        UniversitySessionService.reset_for_tests()
        self.payload = SessionCreate(
            laboratory_id="OCU-LAB-FAILURE-TO-BLOOM-001",
            chapter_id="BITB-CHAPTER-ORCHID-FLOWERING-001",
        )

    def test_create_session_preserves_governance_guards(self) -> None:
        session = UniversitySessionService.create_session("learner-1", self.payload)
        self.assertFalse(session.publication_allowed)
        self.assertFalse(session.automatic_candidate_knowledge)
        self.assertTrue(session.human_review_required)
        self.assertEqual(session.current_stage, "observe")
        self.assertEqual(session.status, "created")

    def test_owner_isolated_session_read(self) -> None:
        session = UniversitySessionService.create_session("learner-1", self.payload)
        with self.assertRaises(UniversityServiceError) as ctx:
            UniversitySessionService.get_session(session.session_id, "learner-2", False)
        self.assertEqual(ctx.exception.code, "SESSION_FORBIDDEN")

    def test_api_key_actor_may_read_for_operations_support(self) -> None:
        session = UniversitySessionService.create_session("learner-1", self.payload)
        loaded = UniversitySessionService.get_session(session.session_id, "service", True)
        self.assertEqual(loaded.session_id, session.session_id)

    def test_stage_may_advance_only_one_step(self) -> None:
        session = UniversitySessionService.create_session("learner-1", self.payload)
        with self.assertRaises(UniversityServiceError) as ctx:
            UniversitySessionService.append_event(
                session.session_id,
                "learner-1",
                False,
                InvestigationEventCreate(
                    event_type="analysis_recorded",
                    stage="analyze",
                    payload={"result": "premature"},
                ),
            )
        self.assertEqual(ctx.exception.code, "INVALID_STAGE_TRANSITION")

    def test_event_append_records_actor_and_revision(self) -> None:
        session = UniversitySessionService.create_session("learner-1", self.payload)
        updated = UniversitySessionService.append_event(
            session.session_id,
            "learner-1",
            False,
            InvestigationEventCreate(
                event_type="observation_added",
                stage="observe",
                payload={"text": "The plant has full-sized growths."},
            ),
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.events[0].actor, "learner-1")
        self.assertEqual(updated.events[0].stage, "observe")

    def test_catalog_rejects_unknown_lab(self) -> None:
        with self.assertRaises(UniversityServiceError) as ctx:
            UniversitySessionService.get_laboratory("OCU-LAB-UNKNOWN")
        self.assertEqual(ctx.exception.code, "LABORATORY_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
