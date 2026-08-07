from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.taxonomy_preflight import Policy
from runtime.taxonomy_preflight_governance import (
    GovernancePolicy,
    deterministic_timestamp,
    execute_bundle,
    validate_report_contract,
    verify_bundle,
)


class TaxonomyGovernanceTests(unittest.TestCase):
    def write_candidate(self, root: Path, text: str = "taxon_id,genus,species\n1,Cattleya,labiata\n") -> Path:
        path = root / "candidate.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_baseline_requirement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "baseline is required"):
                execute_bundle(
                    self.write_candidate(root), None, root / "bundle", Policy(),
                    GovernancePolicy(require_baseline=True),
                )

    def test_candidate_size_and_suffix_are_governed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate.exe"
            candidate.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "suffix is not allowed"):
                execute_bundle(candidate, None, root / "bundle", Policy(), GovernancePolicy())
            candidate = self.write_candidate(root)
            with self.assertRaisesRegex(ValueError, "exceeds governance maximum"):
                execute_bundle(candidate, None, root / "bundle2", Policy(), GovernancePolicy(maximum_candidate_bytes=1))

    def test_source_date_epoch_makes_timestamp_reproducible(self) -> None:
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            self.assertEqual(deterministic_timestamp(), "1970-01-01T00:00:00+00:00")
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "invalid"}):
            with self.assertRaisesRegex(ValueError, "must be an integer"):
                deterministic_timestamp()

    def test_report_contract_rejects_missing_and_wrong_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing keys"):
            validate_report_contract({})
        payload = {
            "report_schema_version": "wrong", "run_id": "x", "source_filename": "x",
            "source_sha256": "x", "generated_at": "x", "validator_version": "0.3.0",
            "status": "PASS", "input_shape": "headered", "metrics": {}, "findings": [],
        }
        with self.assertRaisesRegex(ValueError, "schema version"):
            validate_report_contract(payload)

    def test_governance_violation_converts_report_to_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_candidate(root)
            bundle, receipt = execute_bundle(
                candidate, None, root / "bundle", Policy(),
                GovernancePolicy(maximum_columns=2),
            )
            self.assertEqual(receipt["status"], "FAIL")
            payload = json.loads((bundle / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "governance_violation" for item in payload["findings"]))

    def test_bundle_is_atomic_relocation_safe_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, receipt = execute_bundle(
                self.write_candidate(root), None, root / "bundle", Policy(), GovernancePolicy(),
            )
            self.assertTrue((bundle / "report.json").is_file())
            self.assertTrue((bundle / "summary.md").is_file())
            self.assertTrue((bundle / "manifest.json").is_file())
            self.assertTrue((bundle / "receipt.json").is_file())
            verified = verify_bundle(bundle)
            self.assertTrue(verified["verified"])
            self.assertEqual(verified["run_id"], receipt["run_id"])
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["artifacts"]["report"]["path"], "report.json")

    def test_tampered_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, _ = execute_bundle(
                self.write_candidate(root), None, root / "bundle", Policy(), GovernancePolicy(),
            )
            (bundle / "report.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_bundle(bundle)

    def test_existing_bundle_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_candidate(root)
            output = root / "bundle"
            output.mkdir()
            (output / "sentinel").write_text("keep", encoding="utf-8")
            with self.assertRaises(ValueError):
                execute_bundle(candidate, None, output, Policy(), GovernancePolicy(require_private_output_directory=False))
            self.assertEqual((output / "sentinel").read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
