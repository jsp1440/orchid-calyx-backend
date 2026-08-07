from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.taxonomy_preflight_attestations import GATES, load_and_evaluate


class TaxonomyPreflightAttestationTests(unittest.TestCase):
    def register(self, root: Path, *, statuses: dict[str, str] | None = None) -> Path:
        statuses = statuses or {}
        metadata = {
            "ci_validation": {
                "repository": "jsp1440/orchid-calyx-backend",
                "commit_sha": "a" * 40,
                "workflow_run_id": "31135333766",
            },
            "real_dataset_validation": {
                "source_filename": "WorldOrchids 26-08.csv",
                "source_sha256": "b" * 64,
                "validator_run_id": "run-real-001",
            },
            "billing_credit_linkage": {
                "subscription_id": "sub-001",
                "billing_profile": "Jeffery Parham",
                "credit_expiration": "2027-08-04T00:00:00+00:00",
            },
            "budget_alerts": {"thresholds_percent": [50, 75, 90, 100]},
            "microsoft_architecture_review": {
                "review_reference": "MS-REVIEW-001",
                "reviewer_organization": "Microsoft",
                "review_outcome": "accepted_with_actions",
            },
        }
        payload = {
            "schema_version": "1.0.0",
            "attestations": [
                {
                    "gate": gate,
                    "status": statuses.get(gate, "verified"),
                    "evidence_id": f"evidence-{gate}",
                    "issuer": "test-suite",
                    "issued_at": "2026-08-06T20:00:00+00:00",
                    "evidence_sha256": "c" * 64,
                    "scope": "AZURE-001",
                    "metadata": metadata[gate],
                }
                for gate in GATES
            ],
        }
        path = root / "attestations.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_complete_verified_register_is_valid_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_and_evaluate(
                self.register(Path(tmp)),
                now=datetime(2026, 8, 7, tzinfo=timezone.utc),
            )
            self.assertTrue(result.valid)
            self.assertTrue(all(result.gates.values()))
            self.assertEqual(len(result.evidence_digest), 64)
            self.assertFalse(result.azure_provisioning_authorized)
            self.assertFalse(result.taxonomy_publication_authorized)
            self.assertFalse(result.database_mutation_authorized)
            self.assertFalse(result.production_migration_authorized)

    def test_pending_gate_holds_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_and_evaluate(
                self.register(Path(tmp), statuses={"budget_alerts": "pending"}),
                now=datetime(2026, 8, 7, tzinfo=timezone.utc),
            )
            self.assertFalse(result.valid)
            self.assertFalse(result.gates["budget_alerts"])
            self.assertIn("budget_alerts status is pending", result.reasons)

    def test_duplicate_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.register(Path(tmp))
            payload = json.loads(path.read_text())
            payload["attestations"].append(payload["attestations"][0])
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "duplicate readiness gate"):
                load_and_evaluate(path, now=datetime(2026, 8, 7, tzinfo=timezone.utc))

    def test_future_dated_attestation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.register(Path(tmp))
            payload = json.loads(path.read_text())
            payload["attestations"][0]["issued_at"] = "2030-01-01T00:00:00+00:00"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "future-dated"):
                load_and_evaluate(path, now=datetime(2026, 8, 7, tzinfo=timezone.utc))

    def test_missing_gate_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.register(Path(tmp))
            payload = json.loads(path.read_text())
            payload["attestations"] = payload["attestations"][:-1]
            path.write_text(json.dumps(payload))
            result = load_and_evaluate(path, now=datetime(2026, 8, 7, tzinfo=timezone.utc))
            self.assertFalse(result.valid)
            self.assertTrue(any(reason.startswith("missing attestation") for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
