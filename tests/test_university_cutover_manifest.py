from __future__ import annotations

import json
import tempfile
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
READY_BINDING = {
    "valid": True,
    "frontend_commit": "a" * 40,
    "backend_commit": "b" * 40,
    "frontend_origin": "https://orchidcontinuum.org",
    "api_origin": "https://calyx.example.org/api",
}


def _valid_evidence_bytes() -> bytes:
    payload = {
        "schema_version": "1.1.0",
        "verification": "OCU-SCI-007",
        "release_identity_contract": "OCU-RELEASE-IDENTITY-001",
        "started_at": "2026-08-08T00:00:00Z",
        "completed_at": "2026-08-08T00:01:00Z",
        "frontend_origin": "https://orchidcontinuum.org",
        "api_origin": "https://calyx.example.org/api",
        "frontend": {
            "status": 200,
            "canonical_app_shell": True,
            "release_commit_sha": "a" * 40,
        },
        "backend": {
            "release_identity": {
                "contract": "OCU-RELEASE-IDENTITY-001",
                "service": "orchid-calyx-backend",
                "commit_sha": "b" * 40,
                "attested": True,
            },
            "readiness": {
                "university_enabled": True,
                "read_only_ready": True,
                "session_writes_enabled": False,
                "publication_enabled": False,
                "candidate_knowledge_writes_enabled": False,
                "calyx_model_calls_enabled": False,
                "human_review_required": True,
            },
            "capability": {"enabled": True, "session_writes_enabled": False},
            "catalog": {
                "chapter_id": "BITB-CHAPTER-ORCHID-FLOWERING-001",
                "laboratory_id": "OCU-LAB-FAILURE-TO-BLOOM-001",
            },
            "chapter_sections": 1,
            "laboratory_evidence_items": 1,
        },
        "result": "pass",
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


class UniversityCutoverManifestTests(unittest.TestCase):
    def _generate(self, binding=None, preflight_result=None, **overrides):
        values = {
            "frontend_commit": "a" * 40,
            "backend_commit": "b" * 40,
            "frontend_origin": "https://orchidcontinuum.org",
            "api_origin": "https://calyx.example.org/api",
            "database_url": "postgresql://example",
        }
        values.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            evidence_path = Path(directory) / "evidence.json"
            evidence_path.write_bytes(_valid_evidence_bytes())
            values.setdefault("release_evidence", evidence_path)
            with patch(
                "scripts.generate_university_cutover_manifest._preflight_from_snapshot",
                return_value=preflight_result or READY_PREFLIGHT,
            ), patch(
                "scripts.generate_university_cutover_manifest._release_binding_bytes",
                return_value=binding or READY_BINDING,
            ), patch(
                "scripts.generate_university_cutover_manifest._sha256",
                return_value="sha256:" + "1" * 64,
            ):
                return generate_manifest(**values)

    def test_ready_manifest_is_non_mutating_non_secret_and_attested(self):
        result = self._generate()
        self.assertTrue(result["ready_for_operator_cutover"])
        self.assertFalse(result["mutations_performed"])
        self.assertFalse(result["secrets_included"])
        self.assertFalse(result["reviewer_grants"]["subjects_exposed"])
        self.assertEqual(result["reviewer_grants"]["science"], 1)
        self.assertEqual(result["attested_release"]["frontend_commit"], "a" * 40)
        self.assertEqual(result["attested_release"]["backend_commit"], "b" * 40)
        self.assertTrue(result["release_evidence"]["single_snapshot_bound"])
        self.assertEqual(result["phases"][0]["name"], "read_only_cutover")
        self.assertEqual(result["phases"][3]["name"], "durable_activation")

    def test_manifest_reads_retained_evidence_only_once(self):
        payload = _valid_evidence_bytes()
        evidence_path = Path("replaceable-evidence.json")
        with patch.object(
            Path,
            "read_bytes",
            side_effect=[payload, AssertionError("release evidence was read twice")],
        ) as read_bytes, patch(
            "scripts.generate_university_cutover_manifest._preflight_from_snapshot",
            return_value=READY_PREFLIGHT,
        ) as snapshot_preflight, patch(
            "scripts.generate_university_cutover_manifest._sha256",
            return_value="sha256:" + "1" * 64,
        ):
            result = generate_manifest(
                frontend_commit="a" * 40,
                backend_commit="b" * 40,
                frontend_origin="https://orchidcontinuum.org",
                api_origin="https://calyx.example.org/api",
                release_evidence=evidence_path,
                database_url="postgresql://example",
            )
        self.assertEqual(read_bytes.call_count, 1)
        snapshot_preflight.assert_called_once_with(
            payload,
            database_url="postgresql://example",
        )
        self.assertTrue(result["ready_for_operator_cutover"])
        self.assertEqual(result["attested_release"]["frontend_commit"], "a" * 40)
        self.assertEqual(result["attested_release"]["backend_commit"], "b" * 40)
        self.assertTrue(result["release_evidence"]["single_snapshot_bound"])

    def test_invalid_commit_blocks_cutover(self):
        result = self._generate(frontend_commit="short")
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn(
            "frontend commit must be a full lowercase 40-character Git SHA",
            result["blockers"],
        )

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
        self.assertIn(
            "frontend origin does not match the OCU-SCI-007 evidence origin",
            result["blockers"],
        )

    def test_non_https_origin_blocks_cutover(self):
        result = self._generate(api_origin="http://calyx.example.org/api")
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn("API origin must be an HTTPS origin", result["blockers"])

    def test_invalid_release_binding_blocks_cutover(self):
        result = self._generate(binding={"valid": False, "error": "missing identity"})
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn(
            "release evidence does not contain valid deployed release identities",
            result["blockers"],
        )

    def test_preflight_blockers_are_preserved(self):
        blocked = {
            **READY_PREFLIGHT,
            "blockers": ["qualified science reviewer has not been assigned"],
        }
        result = self._generate(preflight_result=blocked)
        self.assertFalse(result["ready_for_operator_cutover"])
        self.assertIn(
            "qualified science reviewer has not been assigned",
            result["blockers"],
        )

    def test_rollback_never_deletes_audit_records(self):
        result = self._generate()
        joined = " ".join(result["rollback"]["after_phase_3"])
        self.assertIn("preserve database records for audit", joined)


if __name__ == "__main__":
    unittest.main()
