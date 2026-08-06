from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from runtime.taxonomy_preflight import compare_rows, sha256_file, validate


class TaxonomyPreflightTests(unittest.TestCase):
    def write_csv(self, directory: Path, name: str, rows: list[dict[str, str]], fields: list[str] | None = None) -> Path:
        path = directory / name
        fieldnames = fields or list(rows[0].keys())
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_clean_candidate_passes_and_preserves_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_csv(root, "world-orchids.csv", [
                {"taxon_id": "1", "genus": "Cattleya", "species": "labiata"},
                {"taxon_id": "2", "genus": "Dendrobium", "species": "kingianum"},
            ])
            report = validate(candidate)
            self.assertEqual(report.status, "PASS")
            self.assertEqual(report.metrics["row_count"], 2)
            self.assertEqual(report.source_sha256, sha256_file(candidate))
            self.assertEqual(report.source_filename, "world-orchids.csv")

    def test_missing_required_column_fails_without_importing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_csv(root, "bad.csv", [{"genus": "Cattleya"}], fields=["genus"])
            report = validate(candidate)
            self.assertEqual(report.status, "FAIL")
            self.assertTrue(any(item.code == "missing_required_columns" for item in report.findings))

    def test_duplicates_and_malformed_taxa_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_csv(root, "warn.csv", [
                {"taxon_id": "1", "genus": "cattleya", "species": "Labiata"},
                {"taxon_id": "1", "genus": "cattleya", "species": "Labiata"},
            ])
            report = validate(candidate)
            self.assertEqual(report.status, "WARN")
            self.assertEqual(report.metrics["duplicate_taxon_key_count"], 1)
            self.assertEqual(report.metrics["malformed_taxon_name_count"], 2)

    def test_baseline_diff_is_deterministic(self) -> None:
        baseline = [
            {"taxon_id": "1", "genus": "Cattleya", "species": "labiata"},
            {"taxon_id": "2", "genus": "Dendrobium", "species": "kingianum"},
        ]
        candidate = [
            {"taxon_id": "1", "genus": "Cattleya", "species": "labiata", "status": "accepted"},
            {"taxon_id": "3", "genus": "Laelia", "species": "anceps"},
        ]
        first = compare_rows(candidate, baseline)
        second = compare_rows(list(reversed(candidate)), list(reversed(baseline)))
        self.assertEqual(first, second)
        self.assertEqual(first["added"], 1)
        self.assertEqual(first["removed"], 1)
        self.assertEqual(first["changed"], 1)


if __name__ == "__main__":
    unittest.main()
