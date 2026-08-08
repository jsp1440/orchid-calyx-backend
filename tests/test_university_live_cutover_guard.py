from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.verify_university_live_cutover import LiveCutoverError, verify_live_cutover
from scripts.validate_university_release_evidence import EXPECTED_CHAPTER, EXPECTED_LAB, EXPECTED_READINESS

FRONTEND_SHA = "a" * 40
BACKEND_SHA = "b" * 40
FRONTEND_ORIGIN = "https://orchidcontinuum.org"
API_ORIGIN = "https://calyx.example.org/api"


def evidence() -> dict:
    return {
        "schema_version": "1.1.0",
        "verification": "OCU-SCI-007",
        "release_identity_contract": "OCU-RELEASE-IDENTITY-001",
        "started_at": "2026-08-08T00:00:00Z",
        "completed_at": "2026-08-08T00:01:00Z",
        "frontend_origin": FRONTEND_ORIGIN,
        "api_origin": API_ORIGIN,
        "frontend": {
            "url": f"{FRONTEND_ORIGIN}/university/lab",
            "status": 200,
            "canonical_app_shell": True,
            "release_commit_sha": FRONTEND_SHA,
        },
        "backend": {
            "release_identity": {
                "contract": "OCU-RELEASE-IDENTITY-001",
                "service": "orchid-calyx-backend",
                "commit_sha": BACKEND_SHA,
                "attested": True,
                "source": "CALYX_DEPLOYED_COMMIT",
            },
            "readiness": dict(EXPECTED_READINESS),
            "capability": {"enabled": True, "session_writes_enabled": False},
            "catalog": {"chapter_id": EXPECTED_CHAPTER, "laboratory_id": EXPECTED_LAB},
            "chapter_sections": 4,
            "laboratory_evidence_items": 7,
        },
        "result": "pass",
    }


def manifest() -> dict:
    return {
        "contract": "OCU-SCI-009I-CUTOVER-MANIFEST-003",
        "release_identity_contract": "OCU-RELEASE-IDENTITY-001",
        "frontend": {"commit": FRONTEND_SHA, "origin": FRONTEND_ORIGIN},
        "backend": {"commit": BACKEND_SHA, "api_origin": API_ORIGIN},
        "ready_for_operator_cutover": True,
        "mutations_performed": False,
        "secrets_included": False,
    }


def live_html(sha: str = FRONTEND_SHA) -> str:
    return f'<!doctype html><html><head><meta name="ocu-release-sha" content="{sha}" /></head><body><div id="root"></div></body></html>'


def identity(sha: str = BACKEND_SHA) -> dict:
    return {
        "contract": "OCU-RELEASE-IDENTITY-001",
        "service": "orchid-calyx-backend",
        "commit_sha": sha,
        "attested": True,
        "source": "CALYX_DEPLOYED_COMMIT",
    }


def safe_readiness() -> dict:
    return {
        "university_enabled": True,
        "session_writes_enabled": False,
        "publication_enabled": False,
        "candidate_knowledge_writes_enabled": False,
        "calyx_model_calls_enabled": False,
        "human_review_required": True,
        "durable_sessions_enabled": False,
    }


def safe_capability() -> dict:
    return {
        "enabled": True,
        "session_writes_enabled": False,
        "durable_sessions_enabled": False,
        "publication_enabled": False,
        "candidate_knowledge_writes_enabled": False,
        "calyx_model_calls_enabled": False,
    }


class UniversityLiveCutoverGuardTests(unittest.TestCase):
    def _paths(self, directory: str, evidence_payload=None, manifest_payload=None) -> tuple[Path, Path]:
        evidence_path = Path(directory) / "evidence.json"
        manifest_path = Path(directory) / "manifest.json"
        evidence_path.write_text(json.dumps(evidence_payload or evidence()), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest_payload or manifest()), encoding="utf-8")
        return evidence_path, manifest_path

    def _verify(self, evidence_path: Path, manifest_path: Path, *, html=None, backend_identity=None, readiness=None, capability=None):
        responses = {
            f"{API_ORIGIN}/release-identity": backend_identity or identity(),
            f"{API_ORIGIN}/learning/release-readiness": readiness or safe_readiness(),
            f"{API_ORIGIN}/learning/capabilities": capability or safe_capability(),
        }
        with patch("scripts.verify_university_live_cutover._fetch_text", return_value=html or live_html()), patch(
            "scripts.verify_university_live_cutover._fetch_json", side_effect=lambda url: responses[url]
        ):
            return verify_live_cutover(evidence_path=evidence_path, manifest_path=manifest_path)

    def test_matching_live_releases_pass_without_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, manifest_path = self._paths(directory)
            result = self._verify(evidence_path, manifest_path)
        self.assertEqual(result["result"], "pass")
        self.assertEqual(result["frontend_commit"], FRONTEND_SHA)
        self.assertEqual(result["backend_commit"], BACKEND_SHA)
        self.assertTrue(result["safe_pre_activation_state"])
        self.assertFalse(result["mutations_performed"])
        self.assertFalse(result["secrets_included"])

    def test_frontend_redeploy_after_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, manifest_path = self._paths(directory)
            with self.assertRaisesRegex(LiveCutoverError, "live frontend release drifted"):
                self._verify(evidence_path, manifest_path, html=live_html("c" * 40))

    def test_backend_redeploy_after_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, manifest_path = self._paths(directory)
            with self.assertRaisesRegex(LiveCutoverError, "live backend release drifted"):
                self._verify(evidence_path, manifest_path, backend_identity=identity("c" * 40))

    def test_write_enabled_live_state_is_rejected(self) -> None:
        unsafe = safe_readiness()
        unsafe["session_writes_enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, manifest_path = self._paths(directory)
            with self.assertRaisesRegex(LiveCutoverError, "session_writes_enabled must be False"):
                self._verify(evidence_path, manifest_path, readiness=unsafe)

    def test_manifest_commit_mismatch_is_rejected_before_network_checks(self) -> None:
        bad_manifest = manifest()
        bad_manifest["frontend"]["commit"] = "c" * 40
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, manifest_path = self._paths(directory, manifest_payload=bad_manifest)
            with self.assertRaisesRegex(LiveCutoverError, "manifest frontend commit differs from evidence"):
                self._verify(evidence_path, manifest_path)

    def test_legacy_manifest_contract_is_rejected(self) -> None:
        bad_manifest = manifest()
        bad_manifest["contract"] = "OCU-SCI-009I-CUTOVER-MANIFEST-002"
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, manifest_path = self._paths(directory, manifest_payload=bad_manifest)
            with self.assertRaisesRegex(LiveCutoverError, "cutover manifest must use"):
                self._verify(evidence_path, manifest_path)


if __name__ == "__main__":
    unittest.main()
