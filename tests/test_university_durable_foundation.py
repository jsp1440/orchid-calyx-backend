from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.university.durable_config import (
    durable_gate_state,
    durable_sessions_enabled,
    valid_release_evidence_id,
)
from app.university.durable_repository import (
    DurableUniversityError,
    create_session,
    missing_stage_requirements,
    validate_event_stage,
)


class DurableUniversityGateTests(unittest.TestCase):
    def test_durable_sessions_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(durable_sessions_enabled())
            state = durable_gate_state()
            self.assertFalse(state["durable_sessions_enabled"])
            self.assertFalse(state["learner_auth_enabled"])
            self.assertFalse(state["release_evidence_present"])
            self.assertFalse(state["release_evidence_valid"])

    def test_durable_gate_requires_verified_release_evidence(self) -> None:
        env = {
            "OCU_UNIVERSITY_ENABLED": "true",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            "OCU_UNIVERSITY_LEARNER_AUTH_ENABLED": "true",
            "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "true",
            "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(durable_sessions_enabled())

    def test_valid_release_evidence_cannot_bypass_missing_learner_auth(self) -> None:
        env = {
            "OCU_UNIVERSITY_ENABLED": "true",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "true",
            "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
            "OCU_UNIVERSITY_RELEASE_EVIDENCE_ID": "sha256:" + ("a" * 64),
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(durable_sessions_enabled())
            self.assertFalse(durable_gate_state()["learner_auth_enabled"])

    def test_arbitrary_evidence_label_does_not_open_gate(self) -> None:
        env = {
            "OCU_UNIVERSITY_ENABLED": "true",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            "OCU_UNIVERSITY_LEARNER_AUTH_ENABLED": "true",
            "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "true",
            "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
            "OCU_UNIVERSITY_RELEASE_EVIDENCE_ID": "github-actions:example-artifact-id",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(durable_sessions_enabled())
            self.assertFalse(durable_gate_state()["release_evidence_valid"])

    def test_durable_gate_opens_only_with_identity_and_sha256_evidence_reference(self) -> None:
        evidence_id = "sha256:" + ("a" * 64)
        env = {
            "OCU_UNIVERSITY_ENABLED": "true",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "true",
            "OCU_UNIVERSITY_LEARNER_AUTH_ENABLED": "true",
            "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "true",
            "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
            "OCU_UNIVERSITY_RELEASE_EVIDENCE_ID": evidence_id,
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(durable_sessions_enabled())
            self.assertTrue(durable_gate_state()["learner_auth_enabled"])
            self.assertEqual(durable_gate_state()["release_evidence_id"], evidence_id)
            self.assertTrue(durable_gate_state()["release_evidence_valid"])

    def test_release_evidence_identifier_format(self) -> None:
        self.assertTrue(valid_release_evidence_id("sha256:" + ("0" * 64)))
        self.assertFalse(valid_release_evidence_id("sha256:" + ("g" * 64)))
        self.assertFalse(valid_release_evidence_id("artifact-123"))
        self.assertFalse(valid_release_evidence_id(None))

    def test_repository_fails_before_touching_database_when_gate_closed(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://unused"}, clear=True):
            with self.assertRaises(DurableUniversityError) as ctx:
                create_session(
                    laboratory_id="OCU-LAB-FAILURE-TO-BLOOM-001",
                    chapter_id="BITB-CHAPTER-ORCHID-FLOWERING-001",
                    learner_actor="learner-1",
                )
        self.assertEqual(ctx.exception.code, "DURABLE_UNIVERSITY_DISABLED")


class DurableUniversityInquiryPolicyTests(unittest.TestCase):
    def test_each_stage_has_explicit_substantive_exit_requirements(self) -> None:
        self.assertEqual(missing_stage_requirements("observe", []), ("observation_added",))
        self.assertEqual(missing_stage_requirements("question", []), ("question_set",))
        self.assertEqual(
            missing_stage_requirements("investigate", ["hypothesis_added"]),
            ("evidence_examined",),
        )
        self.assertEqual(missing_stage_requirements("analyze", ["analysis_recorded"]), ())
        self.assertEqual(missing_stage_requirements("interpret", ["interpretation_recorded"]), ())
        self.assertEqual(
            missing_stage_requirements("communicate", ["conclusion_drafted"]),
            ("uncertainty_recorded",),
        )
        self.assertEqual(
            missing_stage_requirements(
                "communicate", ["conclusion_drafted", "uncertainty_recorded"]
            ),
            (),
        )

    def test_event_types_are_bound_to_scientific_stage(self) -> None:
        validate_event_stage("observation_added", "observe", "observe")
        validate_event_stage("evidence_examined", "investigate", "investigate")
        validate_event_stage("stage_advanced", "question", "observe")
        with self.assertRaises(DurableUniversityError) as ctx:
            validate_event_stage("observation_added", "question", "question")
        self.assertEqual(ctx.exception.code, "EVENT_STAGE_MISMATCH")
        with self.assertRaises(DurableUniversityError) as ctx:
            validate_event_stage("stage_advanced", "analyze", "question")
        self.assertEqual(ctx.exception.code, "INVALID_STAGE_TRANSITION")


if __name__ == "__main__":
    unittest.main()
