from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.taxonomy_preflight import Policy
from runtime.taxonomy_preflight_governance import GovernancePolicy
from runtime.taxonomy_preflight_release_gate import (
    ReleaseGatePolicy,
    azure_execution_spec,
    execute_release,
    output_lock,
    plan_release,
    verify_release_bundle,
)


class TaxonomyReleaseGateTests(unittest.TestCase):
    def files(self, root: Path) -> tuple[Path, Path]:
        baseline = root / "baseline.csv"
        candidate = root / "candidate.csv"
        content = "taxon_id,scientific_name,status\n1,Cattleya labiata,accepted\n2,Dendrobium kingianum,accepted\n"
        baseline.write_text(content, encoding="utf-8")
        candidate.write_text(content, encoding="utf-8")
        return candidate, baseline

    def policies(self) -> tuple[Policy, GovernancePolicy, ReleaseGatePolicy]:
        return Policy(minimum_rows=2), GovernancePolicy(require_baseline=True, require_private_output_directory=False), ReleaseGatePolicy()

    def test_plan_is_non_mutating_and_records_safety_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, baseline = self.files(root)
            output = root / "bundle"
            validator, governance, release = self.policies()
            result = plan_release(candidate, baseline, output, "OC-REVIEW-1", validator, governance, release)
            self.assertEqual(result["mode"], "plan_only")
            self.assertFalse(output.exists())
            self.assertFalse(result["azure_resources_created"])
            self.assertFalse(result["publication_authorized"])

    def test_review_reference_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, baseline = self.files(root)
            validator, governance, release = self.policies()
            with self.assertRaisesRegex(ValueError, "review reference"):
                plan_release(candidate, baseline, root / "bundle", None, validator, governance, release)

    @unittest.skipIf(os.name == "nt", "symlink behavior differs on Windows")
    def test_symlink_candidate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, baseline = self.files(root)
            link = root / "candidate-link.csv"
            link.symlink_to(candidate)
            validator, governance, release = self.policies()
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                plan_release(link, baseline, root / "bundle", "OC-REVIEW-2", validator, governance, release)

    def test_concurrent_output_lock_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            with output_lock(output):
                with self.assertRaisesRegex(ValueError, "operation is active"):
                    with output_lock(output):
                        pass

    def test_execute_and_verify_release_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, baseline = self.files(root)
            output = root / "bundle"
            validator, governance, release = self.policies()
            result = execute_release(candidate, baseline, output, "OC-REVIEW-3", validator, governance, release)
            self.assertTrue(result["release_verified"])
            self.assertTrue((output / "COMPLETE.json").is_file())
            receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["review_reference"], "OC-REVIEW-3")
            self.assertFalse(receipt["azure_resources_created"])
            verified = verify_release_bundle(output, release)
            self.assertTrue(verified["release_verified"])

    def test_unsafe_receipt_flag_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, baseline = self.files(root)
            output = root / "bundle"
            validator, governance, release = self.policies()
            execute_release(candidate, baseline, output, "OC-REVIEW-4", validator, governance, release)
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["publication_authorized"] = True
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_release_bundle(output, release)

    def test_pinned_azure_spec_is_non_provisioning(self) -> None:
        spec = azure_execution_spec("ghcr.io/fcos/taxonomy@sha256:" + "a" * 64)
        self.assertFalse(spec["provision"])
        self.assertFalse(spec["public_ingress"])
        self.assertFalse(spec["database_access"])
        self.assertTrue(spec["scale_to_zero"])

    def test_unpinned_azure_image_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "pinned"):
            azure_execution_spec("ghcr.io/fcos/taxonomy:latest")


if __name__ == "__main__":
    unittest.main()
