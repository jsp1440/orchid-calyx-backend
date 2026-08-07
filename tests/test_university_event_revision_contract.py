from __future__ import annotations

from datetime import datetime, timezone
import unittest

from app.university.activation_service import _event_to_api
from app.university.schemas import InvestigationEventCreate, SessionCreate
from app.university.service import UniversitySessionService


class UniversityEventRevisionContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        UniversitySessionService.reset_for_tests()

    def test_process_local_event_reports_resulting_session_revision(self) -> None:
        session = UniversitySessionService.create_session(
            "learner-1",
            SessionCreate(
                laboratory_id="OCU-LAB-FAILURE-TO-BLOOM-001",
                chapter_id="BITB-CHAPTER-ORCHID-FLOWERING-001",
            ),
        )
        updated = UniversitySessionService.append_event(
            session.session_id,
            "learner-1",
            False,
            InvestigationEventCreate(
                event_type="observation_added",
                stage="observe",
                payload={"text": "leaf color recorded"},
            ),
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.events[-1].session_revision, 2)

    def test_durable_event_mapping_preserves_database_revision(self) -> None:
        event = _event_to_api(
            {
                "event_id": "11111111-1111-1111-1111-111111111111",
                "event_type": "session_submitted",
                "stage": "contribute",
                "payload": {},
                "actor": "learner-1",
                "session_revision": 9,
                "created_at": datetime.now(timezone.utc),
            }
        )
        self.assertEqual(event["session_revision"], 9)
        self.assertEqual(event["event_type"], "session_submitted")


if __name__ == "__main__":
    unittest.main()
