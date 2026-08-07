from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.taxonomy_preflight_acceptance import evaluate_acceptance


class TaxonomyPreflightAcceptanceTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload: dict[str, object]) -> Path:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def readiness(self, run_id: str, decision: str = "READY_FOR_REVIEW") -> dict[str, object]:
        return {
            "decision": decision,
            "run_id": run_id,
            "azure_provisioning_authorized": False,
            "taxonomy_publication_authorized": False,
            "database_mutation_authorized": False,
        }

    def reproducibility(self, run_id: str, reproducible: bool = True) -> dict[str, object]:
        return {
            "reproducible": reproducible,
            "run_id": run_id,
            "aggregate_digest": "a" * 64,
            "azure_resources_created": False,
            "publication_authorized": False,
            "database_mutation_authorized": False,
        }

    @patch("runtime.taxonomy_preflight_acceptance.verify_release_bundle")
    def test_complete_evidence_is_review_only_not_authority(self, verify) -> None:
        verify.return_value = {"release_verified": True, "run_id": "run-1"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = self.write_json(root, "readiness.json", self.readiness("run-1"))
            reproducibility = self.write_json(root, "reproducibility.json", self.reproducibility("run-1"))
            packet = evaluate_acceptance(root / "bundle", readiness, reproducibility)
            self.assertEqual(packet.decision, "ACCEPTANCE_REVIEW_ONLY")
            self.assertEqual(packet.reasons, ())
            self.assertFalse(packet.azure_provisioning_authorized)
            self.assertFalse(packet.taxonomy_publication_authorized)
            self.assertFalse(packet.database_mutation_authorized)
            self.assertFalse(packet.production_migration_authorized)
            self.assertEqual(len(packet.evidence_digest or ""), 64)

    @patch("runtime.taxonomy_preflight_acceptance.verify_release_bundle")
    def test_hold_readiness_produces_review_only_with_reason(self, verify) -> None:
        verify.return_value = {"release_verified": True, "run_id": "run-1"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = self.write_json(root, "readiness.json", self.readiness("run-1", "HOLD"))
            reproducibility = self.write_json(root, "reproducibility.json", self.reproducibility("run-1"))
            packet = evaluate_acceptance(root / "bundle", readiness, reproducibility)
            self.assertEqual(packet.decision, "REVIEW_ONLY")
            self.assertIn("readiness decision is HOLD", packet.reasons)

    @patch("runtime.taxonomy_preflight_acceptance.verify_release_bundle")
    def test_run_id_mismatch_is_not_accepted(self, verify) -> None:
        verify.return_value = {"release_verified": True, "run_id": "run-1"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = self.write_json(root, "readiness.json", self.readiness("run-2"))
            reproducibility = self.write_json(root, "reproducibility.json", self.reproducibility("run-1"))
            packet = evaluate_acceptance(root / "bundle", readiness, reproducibility)
            self.assertEqual(packet.decision, "REVIEW_ONLY")
            self.assertIn("readiness run_id does not match release bundle", packet.reasons)

    @patch("runtime.taxonomy_preflight_acceptance.verify_release_bundle")
    def test_unsafe_flag_is_rejected(self, verify) -> None:
        verify.return_value = {"release_verified": True, "run_id": "run-1"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness_payload = self.readiness("run-1")
            readiness_payload["azure_provisioning_authorized"] = True
            readiness = self.write_json(root, "readiness.json", readiness_payload)
            reproducibility = self.write_json(root, "reproducibility.json", self.reproducibility("run-1"))
            packet = evaluate_acceptance(root / "bundle", readiness, reproducibility)
            self.assertEqual(packet.decision, "REVIEW_ONLY")
            self.assertTrue(any("azure_provisioning_authorized" in reason for reason in packet.reasons))

    @patch("runtime.taxonomy_preflight_acceptance.verify_release_bundle")
    def test_release_verification_failure_blocks(self, verify) -> None:
        verify.side_effect = ValueError("tampered")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = self.write_json(root, "readiness.json", self.readiness("run-1"))
            reproducibility = self.write_json(root, "reproducibility.json", self.reproducibility("run-1"))
            packet = evaluate_acceptance(root / "bundle", readiness, reproducibility)
            self.assertEqual(packet.decision, "BLOCK")
            self.assertFalse(packet.release_bundle_verified)


if __name__ == "__main__":
    unittest.main()
