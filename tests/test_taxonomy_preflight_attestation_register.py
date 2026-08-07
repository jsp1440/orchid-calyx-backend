from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.taxonomy_preflight_attestation_register import initialize, upsert
from runtime.taxonomy_preflight_attestations import load_and_evaluate


def attestation(gate: str, status: str = "pending") -> dict:
    metadata = {
        "ci_validation": {"repository": "jsp1440/orchid-calyx-backend", "commit_sha": "a" * 40, "workflow_run_id": "1"},
        "real_dataset_validation": {"source_filename": "WorldOrchids.csv", "source_sha256": "b" * 64, "validator_run_id": "run-1"},
        "billing_credit_linkage": {"subscription_id": "sub", "billing_profile": "FCOS", "credit_expiration": "2027-08-04T00:00:00Z"},
        "budget_alerts": {"thresholds_percent": [50, 75, 90, 100]},
        "microsoft_architecture_review": {"review_reference": "MS-1", "reviewer_organization": "Microsoft", "review_outcome": "accepted_with_actions"},
    }[gate]
    return {
        "gate": gate,
        "status": status,
        "evidence_id": f"evidence-{gate}",
        "issuer": "test",
        "issued_at": "2026-08-06T00:00:00Z",
        "evidence_sha256": "c" * 64,
        "scope": "AZURE-001",
        "metadata": metadata,
    }


class AttestationRegisterTests(unittest.TestCase):
    def test_initialize_and_upsert_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            register = root / "register.json"
            initialize(register)
            source = root / "attestation.json"
            source.write_text(json.dumps(attestation("ci_validation")), encoding="utf-8")
            result = upsert(register, source)
            self.assertEqual(result["gate"], "ci_validation")
            payload = json.loads(register.read_text())
            self.assertEqual(payload["attestations"][0]["gate"], "ci_validation")
            self.assertFalse(result["azure_provisioning_authorized"])

    def test_duplicate_requires_explicit_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            register = root / "register.json"
            initialize(register)
            source = root / "attestation.json"
            source.write_text(json.dumps(attestation("ci_validation")), encoding="utf-8")
            upsert(register, source)
            with self.assertRaisesRegex(ValueError, "use --replace"):
                upsert(register, source)
            replacement = attestation("ci_validation", "verified")
            source.write_text(json.dumps(replacement), encoding="utf-8")
            result = upsert(register, source, replace=True)
            self.assertTrue(result["replaced"])

    def test_full_verified_register_passes_canonical_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            register = root / "register.json"
            initialize(register)
            for gate in (
                "ci_validation",
                "real_dataset_validation",
                "billing_credit_linkage",
                "budget_alerts",
                "microsoft_architecture_review",
            ):
                source = root / f"{gate}.json"
                source.write_text(json.dumps(attestation(gate, "verified")), encoding="utf-8")
                upsert(register, source)
            evaluation = load_and_evaluate(register)
            self.assertTrue(evaluation.valid)
            self.assertTrue(all(evaluation.gates.values()))
            self.assertFalse(evaluation.azure_provisioning_authorized)


if __name__ == "__main__":
    unittest.main()
