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
    "configured": True,
    "valid": True,
    "subject_count": 1,
    "science_grant_count": 1,
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

    def _run(self, *, env: dict[str, str] | None = None, evidence=GOOD_EVIDENCE, database=GOOD_DATABASE, registry=GOOD_REGISTRY):
        with patch.dict(os.environ, env or self._env(), clear=True), patch(
            "scripts.preflight_university_activation._release_evidence_state", return_value=evidence
        ), patch(
            "scripts.preflight_university_activation._database_state", return_value=database
        ), patch(
            "scripts.preflight_university_activation._reviewer_registry_state", return_value=registry
        ):
            return preflight(release_evidence=Path("evidence.json"), database_url="postgresql://example")

    def test_ready_only_while_mutating_flags_remain_off_and_reviewer_exists(self) -> None:
        result = self._run()
        self.assertTrue(result["ready_to_enable_durable"])
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["mutations_performed"])

    def test_preflight_blocks_if_session_writes_are_already_enabled(self) -> None:
        env = self._env()
        env["OCU_UNIVERSITY_SESSION_WRITES_ENABLED"] = "true"
        result = self._run(env=env)
        self.assertFalse(result["ready_to_enable_durable"])
        self.assertIn(
            "preflight requires session writes and durable mode to remain disabled",
            result["blockers"],
        )

    def test_preflight_blocks_mismatched_release_evidence(self) -> None:
        result = self._run(evidence={**GOOD_EVIDENCE, "artifact_matches_configured_id": False})
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
        result = self._run(database=database)
        self.assertIn("oc_university durable schema is incomplete or unsafe", result["blockers"])

    def test_preflight_blocks_invalid_reviewer_registry(self) -> None:
        registry = {
            "configured": True,
            "valid": False,
            "subject_count": 0,
            "science_grant_count": 0,
            "expert_grant_count": 0,
            "publication_grant_count": 0,
            "error": "INVALID",
        }
        result = self._run(registry=registry)
        self.assertIn("reviewer qualification registry is invalid", result["blockers"])
        self.assertFalse(result["ready_to_enable_durable"])

    def test_preflight_blocks_until_governance_assigns_a_science_reviewer(self) -> None:
        registry = {
            "configured": False,
            "valid": True,
            "subject_count": 0,
            "science_grant_count": 0,
            "expert_grant_count": 0,
            "publication_grant_count": 0,
        }
        result = self._run(registry=registry)
        self.assertIn(
            "no qualified scientific reviewer is assigned for learner submissions",
            result["blockers"],
        )
        self.assertFalse(result["ready_to_enable_durable"])


if __name__ == "__main__":
    unittest.main()
