from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from runtime.taxonomy_preflight import Policy
from runtime.taxonomy_preflight_governance import GovernancePolicy
from runtime.taxonomy_preflight_release_gate import ReleaseGatePolicy
from runtime.taxonomy_preflight_reproducibility import verify_reproducibility


class TaxonomyPreflightReproducibilityTests(unittest.TestCase):
    def _csv(self, root: Path, name: str) -> Path:
        path = root / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["taxon_id", "scientific_name", "status"])
            writer.writeheader()
            writer.writerow({"taxon_id": "1", "scientific_name": "Cattleya labiata", "status": "accepted"})
            writer.writerow({"taxon_id": "2", "scientific_name": "Dendrobium kingianum", "status": "accepted"})
        return path

    def test_identical_inputs_produce_byte_identical_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._csv(root, "candidate.csv")
            baseline = self._csv(root, "baseline.csv")
            result = verify_reproducibility(
                candidate,
                baseline,
                Policy(minimum_rows=2, maximum_removed_ratio=0.0, maximum_changed_ratio=0.0),
                GovernancePolicy(require_baseline=True, require_private_output_directory=False),
                ReleaseGatePolicy(),
                "TEST-REVIEW-459",
                0,
            )
            self.assertTrue(result["reproducible"])
            self.assertEqual(len(result["aggregate_digest"]), 64)
            self.assertFalse(result["publication_authorized"])
            self.assertFalse(result["database_mutation_authorized"])
            self.assertFalse(result["azure_resources_created"])


if __name__ == "__main__":
    unittest.main()
