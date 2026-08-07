from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.generate_university_cutover_manifest import generate_manifest

READY_PREFLIGHT = {
    "blockers": [],
    "reviewer_registry": {
        "science_grant_count": 1,
        "expert_grant_count": 0,
        "publication_grant_count": 0,
    },
    "ready_to_enable_durable": True,
    "mutations_performed": False,
}


class UniversityCutoverManifestTests(unittest.TestCase):
    def _generate(self, **overrides):
        values = {
            "frontend_commit": "a" * 40,
            "backend_commit": "b" * 40,
            "frontend_origin": "https://orchidcontinuum.org",
            "api_origin": "https://calyx.example.org/api",
            "release_evidence": Path("evidence.json"),
            "database_url": "postgresql://example",
        }
        values.update(overrides)
        with patch("scripts.generate_university_cutover_manifest.preflight", return_value=READY_PREFLIGHT), patch(
            "scripts.generate_university_cutover_manifest._sha256",
            side_effect=["sha256:" + "1" * 64, "sha256:" + "2" * 64],
        ), patch.object(Path, "exists", return_value=True):
            return generate_manifest(**values)

    def test_ready_manifest_is_non_mutating_and_non_secret(self):
        result = self._generate()
        self.assertTrue(result["ready_for_operator_cutover"])
        self.assertFalse(result["mutations_performed"])
        self.assertFalse(result["secrets_included"])
        self.assertFalse(result["reviewer_grants"]["subjects_exposed"])
        self.assertEqual(result["reviewer_grants"]["science"], 1)
        self.assertEqual(result["phases"][0]["name"], "read_only_cutover")
        self.assertEqual(result["phases"][3]["name"], "durable_activation")

    def test_invalid_commit_blocks_cutover(self):
        result = self._generate(frontend_commit="short")
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("frontend commit must be a full lowercase 40-character Git SHA", result["blockers"])

    def test_non_https_origin_blocks_cutover(self):
        result = self._generate(api_origin="http://calyx.example.org/api")
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("API origin must be an HTTPS origin", result["blockers"])

    def test_preflight_blockers_are_preserved(self):
        blocked = {**READY_PREFLIGHT, "blockers": ["qualified science reviewer has not been assigned"]}
        with patch("scripts.generate_university_cutover_manifest.preflight", return_value=blocked), patch(
            "scripts.generate_university_cutover_manifest._sha256",
            side_effect=["sha256:" + "1" * 64, "sha256:" + "2" * 64],
        ), patch.object(Path, "exists", return_value=True):
            result = generate_manifest(
                frontend_commit="a" * 40,
                backend_commit="b" * 40,
                frontend_origin="https://orchidcontinuum.org",
                api_origin="https://calyx.example.org/api",
                release_evidence=Path("evidence.json"),
                database_url="postgresql://example",
            )
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("qualified science reviewer has not been assigned", result["blockers"])

    def test_rollback_never_deletes_audit_records(self):
        result = self._generate()
        joined = " ".join(result["rollback"]["after_phase_3"])
        self.assertIn("preserve database records for audit", joined)


if __name__ == "__main__":
    unittest.main()
