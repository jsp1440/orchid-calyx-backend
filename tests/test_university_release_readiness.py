from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.university.release import release_readiness


class UniversityReleaseReadinessTests(unittest.TestCase):
    def test_disabled_configuration_is_not_read_only_ready(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = release_readiness()
        self.assertEqual(result["release_contract"], "OCU-RELEASE-003")
        self.assertFalse(result["university_enabled"])
        self.assertFalse(result["read_only_ready"])
        self.assertFalse(result["session_writes_enabled"])
        self.assertFalse(result["learner_auth_enabled"])
        self.assertFalse(result["durable_sessions_enabled"])
        self.assertEqual(result["persistence"], "process_local_memory")

    def test_safe_read_only_configuration_is_ready_without_learner_auth(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OCU_UNIVERSITY_ENABLED": "true",
                "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "false",
            },
            clear=True,
        ):
            result = release_readiness()
        self.assertTrue(result["read_only_ready"])
        self.assertFalse(result["session_writes_enabled"])
        self.assertFalse(result["learner_auth_enabled"])
        self.assertFalse(result["durable_sessions_enabled"])
        self.assertEqual(result["persistence"], "process_local_memory")
        self.assertFalse(result["publication_enabled"])
        self.assertFalse(result["candidate_knowledge_writes_enabled"])
        self.assertFalse(result["calyx_model_calls_enabled"])
        self.assertTrue(result["human_review_required"])

    def test_write_enabled_without_learner_auth_is_not_durable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OCU_UNIVERSITY_ENABLED": "true",
                "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
                "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "true",
                "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
                "OCU_UNIVERSITY_RELEASE_EVIDENCE_ID": "sha256:" + "a" * 64,
            },
            clear=True,
        ):
            result = release_readiness()
        self.assertFalse(result["read_only_ready"])
        self.assertTrue(result["session_writes_enabled"])
        self.assertFalse(result["learner_auth_enabled"])
        self.assertFalse(result["durable_sessions_enabled"])
        self.assertFalse(result["durable_gate"]["learner_auth_enabled"])

    def test_verified_durable_gate_reports_postgres_without_weakening_safety_flags(self) -> None:
        durable_state = {
            "session_writes_enabled": True,
            "learner_auth_enabled": True,
            "durable_flag_enabled": True,
            "read_only_release_verified": True,
            "release_evidence_present": True,
            "release_evidence_valid": True,
            "release_evidence_id": "sha256:" + "a" * 64,
            "durable_sessions_enabled": True,
        }
        with patch.dict(
            os.environ,
            {
                "OCU_UNIVERSITY_ENABLED": "true",
                "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
                "OCU_UNIVERSITY_LEARNER_AUTH_ENABLED": "true",
            },
            clear=True,
        ), patch(
            "app.university.release.durable_sessions_enabled", return_value=True
        ), patch(
            "app.university.release.durable_gate_state", return_value=durable_state
        ):
            result = release_readiness()
        self.assertFalse(result["read_only_ready"])
        self.assertTrue(result["session_writes_enabled"])
        self.assertTrue(result["learner_auth_enabled"])
        self.assertTrue(result["durable_sessions_enabled"])
        self.assertEqual(result["persistence"], "postgres_durable")
        self.assertEqual(result["durable_gate"], durable_state)
        self.assertFalse(result["publication_enabled"])
        self.assertFalse(result["candidate_knowledge_writes_enabled"])
        self.assertFalse(result["calyx_model_calls_enabled"])
        self.assertTrue(result["human_review_required"])


if __name__ == "__main__":
    unittest.main()
