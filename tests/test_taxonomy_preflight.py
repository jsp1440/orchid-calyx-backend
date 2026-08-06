from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from runtime.taxonomy_preflight import compare_rows, load_csv, sha256_file, validate


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
            self.assertEqual(report.input_shape, "headered")
            self.assertEqual(report.metrics["row_count"], 2)
            self.assertEqual(report.source_sha256, sha256_file(candidate))

    def test_scientific_name_column_is_valid_alternative_to_split_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_csv(root, "names.csv", [
                {"scientific_name": "Cattleya labiata Lindl.", "status": "accepted"},
            ])
            report = validate(candidate)
            self.assertEqual(report.status, "PASS")

    def test_missing_identity_columns_fails_without_importing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_csv(root, "bad.csv", [{"publication": "Example"}], fields=["publication"])
            report = validate(candidate)
            self.assertEqual(report.status, "FAIL")
            self.assertTrue(any(item.code == "missing_taxon_identity_columns" for item in report.findings))

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

    def test_legacy_world_plants_pipe_export_is_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "WorldOrchids-26-08.csv"
            path.write_text(
                "S||Maxillaria gualaquizensis Dodson|Orquideologia 19(3): 69 (1994)||Ecuador; Peru|= Laricorchis gualaquizensis (Dodson) Szlach. & Sitko||||\n"
                "S||Cattleya labiata Lindl.|Collectanea Botanica t. 33 (1824)||Brazil|||\n",
                encoding="utf-8",
            )
            columns, rows, _, delimiter, shape = load_csv(path)
            self.assertEqual(delimiter, "|")
            self.assertEqual(shape, "legacy_world_plants_headerless")
            self.assertEqual(columns[2], "scientific_name")
            self.assertEqual(rows[0]["scientific_name"], "Maxillaria gualaquizensis Dodson")
            report = validate(path)
            self.assertEqual(report.status, "PASS")
            self.assertEqual(report.metrics["row_count"], 2)

    def test_unknown_headerless_shape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown.csv"
            path.write_text("Cattleya,labiata\nDendrobium,kingianum\n", encoding="utf-8")
            report = validate(path)
            self.assertEqual(report.status, "FAIL")
            self.assertTrue(any(item.code == "unknown_headerless_shape" for item in report.findings))

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
