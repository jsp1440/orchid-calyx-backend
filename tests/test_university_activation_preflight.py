from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.preflight_university_activation import preflight


GOOD_EVIDENCE = {
    "configured_id_present": True,
    "configured_id_valid": True,
    "artifact_supplied": True,
    "artifact_valid": True,
    "artifact_matches_configured_id": True,
    "artifact_digest": "sha256:" + "a" * 64,
}
GOOD_DATABASE = {
    "configured": True,
    "reachable": True,
    "schema_valid": True,
    "missing_columns": {},
    "missing_constraint_fragments": [],
}
GOOD_REGISTRY = {
    "configured": False,
    "valid": True,
    "subject_count": 0,
    "science_grant_count": 0,
    "expert_grant_count": 0,
    "publication_grant_count": 0,
}


class UniversityActivationPreflightTests(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        return {
            "OCU_UNIVERSITY_ENABLED": "true",
            "OCU_UNIVERSITY_LEARNER_AUTH_ENABLED": "true",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED": "false",
            "OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED": "false",
            "OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED": "true",
            "OCU_UNIVERSITY_RELEASE_EVIDENCE_ID": "sha256:" + "a" * 64,
            "OCU_SUPABASE_URL": "https://example.supabase.co",
            "OCU_SUPABASE_ANON_KEY": "public-anon-key",
        }

    def test_ready_only_while_mutating_flags_remain_off(self) -> None:
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "scripts.preflight_university_activation._release_evidence_state",
            return_value=GOOD_EVIDENCE,
        ), patch(
            "scripts.preflight_university_activation._database_state",
            return_value=GOOD_DATABASE,
        ), patch(
            "scripts.preflight_university_activation._reviewer_registry_state",
            return_value=GOOD_REGISTRY,
        ):
            result = preflight(release_evidence=Path("evidence.json"), database_url="postgresql://example")
        self.assertTrue(result["ready_to_enable_durable"])
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["mutations_performed"])

    def test_preflight_blocks_if_session_writes_are_already_enabled(self) -> None:
        env = self._env()
        env["OCU_UNIVERSITY_SESSION_WRITES_ENABLED"] = "true"
        with patch.dict(os.environ, env, clear=True), patch(
            "scripts.preflight_university_activation._release_evidence_state",
            return_value=GOOD_EVIDENCE,
        ), patch(
            "scripts.preflight_university_activation._database_state",
            return_value=GOOD_DATABASE,
        ), patch(
            "scripts.preflight_university_activation._reviewer_registry_state",
            return_value=GOOD_REGISTRY,
        ):
            result = preflight(release_evidence=Path("evidence.json"), database_url="postgresql://example")
        self.assertFalse(result["ready_to_enable_durable"])
        self.assertIn(
            "preflight requires session writes and durable mode to remain disabled",
            result["blockers"],
        )

    def test_preflight_blocks_mismatched_release_evidence(self) -> None:
        evidence = {**GOOD_EVIDENCE, "artifact_matches_configured_id": False}
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "scripts.preflight_university_activation._release_evidence_state",
            return_value=evidence,
        ), patch(
            "scripts.preflight_university_activation._database_state",
            return_value=GOOD_DATABASE,
        ), patch(
            "scripts.preflight_university_activation._reviewer_registry_state",
            return_value=GOOD_REGISTRY,
        ):
            result = preflight(release_evidence=Path("evidence.json"), database_url="postgresql://example")
        self.assertIn(
            "release evidence artifact does not match configured SHA-256 evidence ID",
            result["blockers"],
        )

    def test_preflight_blocks_incomplete_database_schema(self) -> None:
        database = {
            **GOOD_DATABASE,
            "schema_valid": False,
            "missing_columns": {"session_reviews": ["reviewer_qualifications"]},
        }
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "scripts.preflight_university_activation._release_evidence_state",
            return_value=GOOD_EVIDENCE,
        ), patch(
            "scripts.preflight_university_activation._database_state",
            return_value=database,
        ), patch(
            "scripts.preflight_university_activation._reviewer_registry_state",
            return_value=GOOD_REGISTRY,
        ):
            result = preflight(release_evidence=Path("evidence.json"), database_url="postgresql://example")
        self.assertIn("oc_university durable schema is incomplete or unsafe", result["blockers"])

    def test_preflight_blocks_invalid_reviewer_registry_without_requiring_a_grant(self) -> None:
        registry = {"configured": True, "valid": False, "subject_count": 0, "error": "INVALID"}
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "scripts.preflight_university_activation._release_evidence_state",
            return_value=GOOD_EVIDENCE,
        ), patch(
            "scripts.preflight_university_activation._database_state",
            return_value=GOOD_DATABASE,
        ), patch(
            "scripts.preflight_university_activation._reviewer_registry_state",
            return_value=registry,
        ):
            result = preflight(release_evidence=Path("evidence.json"), database_url="postgresql://example")
        self.assertIn("reviewer qualification registry is invalid", result["blockers"])
        self.assertFalse(result["ready_to_enable_durable"])


if __name__ == "__main__":
    unittest.main()
