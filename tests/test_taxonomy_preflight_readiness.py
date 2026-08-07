from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.taxonomy_preflight_readiness import evaluate


class TaxonomyPreflightReadinessTests(unittest.TestCase):
    @patch("runtime.taxonomy_preflight_readiness.verify_bundle")
    def test_missing_external_gates_hold_without_granting_authority(self, verify) -> None:
        verify.return_value = {"verified": True, "run_id": "run-1"}
        decision = evaluate(
            Path("bundle"),
            ci_validated=True,
            real_dataset_validated=False,
            billing_credit_verified=True,
            budget_alerts_configured=False,
            microsoft_review_complete=False,
        )
        self.assertEqual(decision.decision, "HOLD")
        self.assertEqual(decision.evidence_mode, "legacy_flags")
        self.assertFalse(decision.azure_provisioning_authorized)
        self.assertFalse(decision.taxonomy_publication_authorized)
        self.assertFalse(decision.database_mutation_authorized)
        self.assertFalse(decision.production_migration_authorized)
        self.assertIn("exact World Orchids dataset validation is incomplete", decision.reasons)

    @patch("runtime.taxonomy_preflight_readiness.verify_bundle")
    def test_all_gates_only_reaches_ready_for_review(self, verify) -> None:
        verify.return_value = {"verified": True, "run_id": "run-2"}
        decision = evaluate(
            Path("bundle"),
            ci_validated=True,
            real_dataset_validated=True,
            billing_credit_verified=True,
            budget_alerts_configured=True,
            microsoft_review_complete=True,
        )
        self.assertEqual(decision.decision, "READY_FOR_REVIEW")
        self.assertEqual(decision.reasons, ())
        self.assertFalse(decision.azure_provisioning_authorized)

    @patch("runtime.taxonomy_preflight_readiness.verify_bundle")
    @patch("runtime.taxonomy_preflight_readiness.load_and_evaluate")
    def test_typed_attestations_replace_cli_booleans(self, load_attestations, verify) -> None:
        verify.return_value = {"verified": True, "run_id": "run-3"}
        load_attestations.return_value.gates = {
            "ci_validation": True,
            "real_dataset_validation": True,
            "billing_credit_linkage": True,
            "budget_alerts": False,
            "microsoft_architecture_review": True,
        }
        load_attestations.return_value.reasons = ("budget_alerts status is pending",)
        load_attestations.return_value.evidence_digest = "d" * 64
        decision = evaluate(
            Path("bundle"),
            ci_validated=True,
            real_dataset_validated=True,
            billing_credit_verified=True,
            budget_alerts_configured=True,
            microsoft_review_complete=True,
            attestation_path=Path("attestations.json"),
        )
        self.assertEqual(decision.decision, "HOLD")
        self.assertEqual(decision.evidence_mode, "typed_attestations")
        self.assertEqual(decision.evidence_digest, "d" * 64)
        self.assertFalse(decision.budget_alerts_configured)

    @patch("runtime.taxonomy_preflight_readiness.verify_bundle")
    def test_invalid_bundle_blocks(self, verify) -> None:
        verify.side_effect = ValueError("checksum mismatch")
        decision = evaluate(
            Path("bundle"),
            ci_validated=True,
            real_dataset_validated=True,
            billing_credit_verified=True,
            budget_alerts_configured=True,
            microsoft_review_complete=True,
        )
        self.assertEqual(decision.decision, "BLOCK")
        self.assertIn("checksum mismatch", decision.reasons[0])


if __name__ == "__main__":
    unittest.main()
