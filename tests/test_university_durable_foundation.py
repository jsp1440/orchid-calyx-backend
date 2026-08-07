from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.university.durable_config import durable_gate_state, durable_sessions_enabled
from app.university.durable_repository import DurableUniversityError, create_session


class DurableUniversityGateTests(unittest.TestCase):
    def test_durable_sessions_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(durable_sessions_enabled())
            state = durable_gate_state()
            self.assertFalse(state["durable_sessions_enabled"])
            self.assertFalse(state["release_evidence_present"])

    def test_durable_gate_requires_verified_release_evidence(self) -> None:
        env = {
            "OCU_UNIVERSITY_ENABLED": "true",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "true",
            "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(durable_sessions_enabled())

    def test_durable_gate_opens_only_with_all_explicit_controls(self) -> None:
        env = {
            "OCU_UNIVERSITY_ENABLED": "true",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "true",
            "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
            "OCU_UNIVERSITY_RELEASE_EVIDENCE_ID": "github-actions:example-artifact-id",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(durable_sessions_enabled())
            self.assertEqual(
                durable_gate_state()["release_evidence_id"],
                "github-actions:example-artifact-id",
            )

    def test_repository_fails_before_touching_database_when_gate_closed(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://unused"}, clear=True):
            with self.assertRaises(DurableUniversityError) as ctx:
                create_session(
                    laboratory_id="OCU-LAB-FAILURE-TO-BLOOM-001",
                    chapter_id="BITB-CHAPTER-ORCHID-FLOWERING-001",
                    learner_actor="learner-1",
                )
        self.assertEqual(ctx.exception.code, "DURABLE_UNIVERSITY_DISABLED")


if __name__ == "__main__":
    unittest.main()
