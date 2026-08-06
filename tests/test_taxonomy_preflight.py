from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from runtime.taxonomy_preflight import (
    Policy,
    atomic_write_text,
    compare_rows,
    load_csv,
    sha256_file,
    validate,
    write_human_summary,
    write_manifest,
)


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
            self.assertEqual(report.report_schema_version, "1.0.0")
            self.assertEqual(report.input_shape, "headered")
            self.assertEqual(report.metrics["row_count"], 2)
            self.assertEqual(report.source_sha256, sha256_file(candidate))
            self.assertEqual(len(report.run_id), 24)

    def test_run_id_is_deterministic_for_same_inputs_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_csv(root, "candidate.csv", [{"scientific_name": "Cattleya labiata"}])
            self.assertEqual(validate(candidate).run_id, validate(candidate).run_id)
            self.assertNotEqual(validate(candidate).run_id, validate(candidate, policy=Policy(minimum_rows=0)).run_id)

    def test_scientific_name_column_is_valid_alternative_to_split_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.write_csv(Path(tmp), "names.csv", [{"scientific_name": "Cattleya labiata Lindl.", "status": "accepted"}])
            self.assertEqual(validate(candidate).status, "PASS")

    def test_missing_identity_columns_fails_without_importing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.write_csv(Path(tmp), "bad.csv", [{"publication": "Example"}], fields=["publication"])
            report = validate(candidate)
            self.assertEqual(report.status, "FAIL")
            self.assertTrue(any(item.code == "missing_taxon_identity_columns" for item in report.findings))

    def test_duplicates_and_malformed_taxa_can_warn_under_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.write_csv(Path(tmp), "warn.csv", [
                {"taxon_id": "1", "genus": "cattleya", "species": "Labiata"},
                {"taxon_id": "1", "genus": "cattleya", "species": "Labiata"},
            ])
            report = validate(candidate, policy=Policy(maximum_duplicate_key_ratio=1.0))
            self.assertEqual(report.status, "WARN")
            self.assertEqual(report.metrics["duplicate_taxon_key_count"], 1)
            self.assertEqual(report.finding_counts["WARN:malformed_taxon_name"], 2)

    def test_duplicate_ratio_fails_closed_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.write_csv(Path(tmp), "duplicate.csv", [
                {"taxon_id": "1", "scientific_name": "Cattleya labiata"},
                {"taxon_id": "1", "scientific_name": "Cattleya labiata"},
            ])
            report = validate(candidate)
            self.assertEqual(report.status, "FAIL")
            self.assertIn("FAIL:duplicate_ratio_exceeded", report.finding_counts)

    def test_legacy_world_plants_pipe_export_is_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "WorldOrchids-26-08.csv"
            path.write_text(
                "S||Maxillaria gualaquizensis Dodson|Orquideologia 19(3): 69 (1994)||Ecuador; Peru|= Laricorchis gualaquizensis (Dodson) Szlach. & Sitko||||\n"
                "S||Cattleya labiata Lindl.|Collectanea Botanica t. 33 (1824)||Brazil|||\n",
                encoding="utf-8",
            )
            columns, rows, _, delimiter, shape, width_anomalies = load_csv(path)
            self.assertEqual(delimiter, "|")
            self.assertEqual(shape, "legacy_world_plants_headerless")
            self.assertEqual(columns[2], "scientific_name")
            self.assertEqual(rows[0]["scientific_name"], "Maxillaria gualaquizensis Dodson")
            self.assertGreaterEqual(width_anomalies, 0)
            report = validate(path)
            self.assertEqual(report.status, "PASS")
            self.assertEqual(report.metrics["record_type_counts"], {"S": 2})

    def test_unknown_headerless_shape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown.csv"
            path.write_text("Cattleya,labiata\nDendrobium,kingianum\n", encoding="utf-8")
            self.assertEqual(validate(path).status, "FAIL")

    def test_baseline_change_thresholds_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.write_csv(root, "baseline.csv", [
                {"taxon_id": "1", "scientific_name": "Cattleya labiata"},
                {"taxon_id": "2", "scientific_name": "Dendrobium kingianum"},
            ])
            candidate = self.write_csv(root, "candidate.csv", [{"taxon_id": "1", "scientific_name": "Cattleya labiata", "status": "accepted"}])
            report = validate(candidate, baseline)
            self.assertEqual(report.status, "FAIL")
            self.assertIn("FAIL:removed_ratio_exceeded", report.finding_counts)
            self.assertEqual(report.baseline_sha256, sha256_file(baseline))

    def test_baseline_diff_is_deterministic_and_has_ratios(self) -> None:
        baseline = [
            {"taxon_id": "1", "genus": "Cattleya", "species": "labiata"},
            {"taxon_id": "2", "genus": "Dendrobium", "species": "kingianum"},
        ]
        candidate = [
            {"taxon_id": "1", "genus": "Cattleya", "species": "labiata", "status": "accepted"},
            {"taxon_id": "3", "genus": "Laelia", "species": "anceps"},
        ]
        first = compare_rows(candidate, baseline)
        self.assertEqual(first, compare_rows(list(reversed(candidate)), list(reversed(baseline))))
        self.assertEqual(first["removed_ratio"], 0.5)
        self.assertEqual(first["changed_ratio"], 0.5)

    def test_policy_file_rejects_unknown_fields_and_bad_ratios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unknown = root / "unknown.json"
            unknown.write_text('{"surprise": 1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                Policy.from_path(unknown)
            bad = root / "bad.json"
            bad.write_text('{"maximum_removed_ratio": 2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                Policy.from_path(bad)

    def test_atomic_outputs_and_manifest_are_checksummed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self.write_csv(root, "candidate.csv", [{"scientific_name": "Cattleya labiata"}])
            report = validate(candidate)
            report_path, summary_path, manifest_path = root / "report.json", root / "summary.md", root / "manifest.json"
            atomic_write_text(report_path, json.dumps(report.to_dict(), sort_keys=True))
            write_human_summary(report, summary_path)
            write_manifest(report, report_path, summary_path, manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], report.run_id)
            self.assertEqual(manifest["artifacts"]["report"]["sha256"], sha256_file(report_path))
            self.assertEqual(manifest["artifacts"]["summary"]["sha256"], sha256_file(summary_path))

    def test_missing_input_path_raises_controlled_error(self) -> None:
        with self.assertRaises(ValueError):
            validate(Path("does-not-exist.csv"))


if __name__ == "__main__":
    unittest.main()
