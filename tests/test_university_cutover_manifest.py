from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.generate_university_cutover_manifest import generate_manifest

READY_PREFLIGHT = {
    "migration_blockers": [],
    "durable_blockers": [],
    "blockers": [],
    "reviewer_registry": {
        "science_grant_count": 1,
        "expert_grant_count": 0,
        "publication_grant_count": 0,
    },
    "ready_to_apply_migration": True,
    "ready_to_enable_durable": True,
    "mutations_performed": False,
}
PRE_MIGRATION_PREFLIGHT = {
    **READY_PREFLIGHT,
    "durable_blockers": ["oc_university durable schema is incomplete or unsafe"],
    "blockers": ["oc_university durable schema is incomplete or unsafe"],
    "ready_to_enable_durable": False,
}
READY_BINDING = {
    "valid": True,
    "frontend_commit": "a" * 40,
    "backend_commit": "b" * 40,
    "frontend_origin": "https://orchidcontinuum.org",
    "api_origin": "https://calyx.example.org/api",
}


class UniversityCutoverManifestTests(unittest.TestCase):
    def _generate(self, binding=None, preflight_state=READY_PREFLIGHT, **overrides):
        values = {
            "frontend_commit": "a" * 40,
            "backend_commit": "b" * 40,
            "frontend_origin": "https://orchidcontinuum.org",
            "api_origin": "https://calyx.example.org/api",
            "release_evidence": Path("evidence.json"),
            "database_url": "postgresql://example",
        }
        values.update(overrides)
        with patch("scripts.generate_university_cutover_manifest.preflight", return_value=preflight_state), patch(
            "scripts.generate_university_cutover_manifest._release_binding",
            return_value=binding or READY_BINDING,
        ), patch(
            "scripts.generate_university_cutover_manifest._sha256",
            side_effect=["sha256:" + "1" * 64, "sha256:" + "2" * 64],
        ), patch.object(Path, "exists", return_value=True):
            return generate_manifest(**values)

    def test_ready_manifest_is_non_mutating_non_secret_and_attested(self):
        result = self._generate()
        self.assertEqual(result["contract"], "OCU-SCI-009I-CUTOVER-MANIFEST-003")
        self.assertTrue(result["ready_for_operator_cutover"])
        self.assertTrue(result["gates"]["ready_to_apply_migration"])
        self.assertTrue(result["gates"]["ready_to_enable_durable"])
        self.assertTrue(result["gates"]["durable_gate_requires_post_migration_rerun"])
        self.assertFalse(result["mutations_performed"])
        self.assertFalse(result["secrets_included"])
        self.assertFalse(result["reviewer_grants"]["subjects_exposed"])
        self.assertEqual(result["reviewer_grants"]["science"], 1)
        self.assertEqual(result["attested_release"]["frontend_commit"], "a" * 40)
        self.assertEqual(result["attested_release"]["backend_commit"], "b" * 40)
        self.assertEqual(result["phases"][1]["requires"][-1], "preflight.ready_to_apply_migration=true")
        self.assertEqual(result["phases"][2]["requires"][-1], "preflight.ready_to_enable_durable=true")

    def test_missing_schema_does_not_block_starting_database_migration(self):
        result = self._generate(preflight_state=PRE_MIGRATION_PREFLIGHT)
        self.assertTrue(result["ready_for_operator_cutover"])
        self.assertTrue(result["gates"]["ready_to_apply_migration"])
        self.assertFalse(result["gates"]["ready_to_enable_durable"])
        self.assertNotIn("oc_university durable schema is incomplete or unsafe", result["blockers"])

    def test_migration_gate_blockers_block_operator_cutover(self):
        blocked = {
            **PRE_MIGRATION_PREFLIGHT,
            "migration_blockers": ["qualified science reviewer has not been assigned"],
            "ready_to_apply_migration": False,
        }
        result = self._generate(preflight_state=blocked)
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("qualified science reviewer has not been assigned", result["blockers"])

    def test_invalid_commit_blocks_cutover(self):
        result = self._generate(frontend_commit="short")
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("frontend commit must be a full lowercase 40-character Git SHA", result["blockers"])

    def test_typed_frontend_commit_must_match_attested_release(self):
        result = self._generate(frontend_commit="c" * 40)
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn(
            "frontend commit does not match the release attested by OCU-SCI-007 evidence",
            result["blockers"],
        )

    def test_typed_backend_commit_must_match_attested_release(self):
        result = self._generate(backend_commit="c" * 40)
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn(
            "backend commit does not match the release attested by OCU-SCI-007 evidence",
            result["blockers"],
        )

    def test_origins_must_match_attested_evidence(self):
        result = self._generate(frontend_origin="https://app.orchidcontinuum.org")
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("frontend origin does not match the OCU-SCI-007 evidence origin", result["blockers"])

    def test_non_https_origin_blocks_cutover(self):
        result = self._generate(api_origin="http://calyx.example.org/api")
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("API origin must be an HTTPS origin", result["blockers"])

    def test_invalid_release_binding_blocks_cutover(self):
        result = self._generate(binding={"valid": False, "error": "missing identity"})
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("release evidence does not contain valid deployed release identities", result["blockers"])

    def test_rollback_never_deletes_audit_records(self):
        result = self._generate()
        joined = " ".join(result["rollback"]["after_phase_3"])
        self.assertIn("preserve database records for audit", joined)


if __name__ == "__main__":
    unittest.main()
