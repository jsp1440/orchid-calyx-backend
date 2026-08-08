from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate_university_release_evidence.py"
SPEC = importlib.util.spec_from_file_location("release_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_artifact() -> dict:
    return {
        "schema_version": "1.1.0",
        "verification": "OCU-SCI-007",
        "release_identity_contract": "OCU-RELEASE-IDENTITY-001",
        "started_at": "2026-08-08T00:00:00Z",
        "completed_at": "2026-08-08T00:01:00Z",
        "frontend_origin": "https://orchidcontinuum.org",
        "api_origin": "https://calyx.example.org/api",
        "frontend": {
            "url": "https://orchidcontinuum.org/university/lab",
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
                "source": "CALYX_DEPLOYED_COMMIT",
            },
            "readiness": dict(MODULE.EXPECTED_READINESS),
            "capability": {"enabled": True, "session_writes_enabled": False},
            "catalog": {
                "chapter_id": MODULE.EXPECTED_CHAPTER,
                "laboratory_id": MODULE.EXPECTED_LAB,
            },
            "chapter_sections": 4,
            "laboratory_evidence_items": 7,
        },
        "result": "pass",
    }


class ReleaseEvidenceTests(unittest.TestCase):
    def test_passing_artifact_validates(self) -> None:
        artifact = valid_artifact()
        MODULE.validate_evidence(artifact)
        self.assertEqual(MODULE.release_commits(artifact), ("a" * 40, "b" * 40))

    def test_failed_artifact_is_rejected(self) -> None:
        artifact = valid_artifact()
        artifact["result"] = "fail"
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_evidence(artifact)

    def test_write_enabled_artifact_is_rejected(self) -> None:
        artifact = valid_artifact()
        artifact["backend"]["readiness"]["session_writes_enabled"] = True
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_evidence(artifact)

    def test_noncanonical_frontend_is_rejected(self) -> None:
        artifact = valid_artifact()
        artifact["frontend"]["canonical_app_shell"] = False
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_evidence(artifact)

    def test_missing_frontend_release_identity_is_rejected(self) -> None:
        artifact = valid_artifact()
        artifact["frontend"].pop("release_commit_sha")
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_evidence(artifact)

    def test_unattested_backend_release_identity_is_rejected(self) -> None:
        artifact = valid_artifact()
        artifact["backend"]["release_identity"]["attested"] = False
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_evidence(artifact)

    def test_legacy_schema_is_rejected(self) -> None:
        artifact = valid_artifact()
        artifact["schema_version"] = "1.0.0"
        with self.assertRaises(MODULE.EvidenceError):
            MODULE.validate_evidence(artifact)

    def test_digest_uses_sha256_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text("{}\n", encoding="utf-8")
            digest = MODULE.evidence_digest(path)
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
