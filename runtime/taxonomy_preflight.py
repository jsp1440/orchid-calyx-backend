"""Deterministic, non-publishing taxonomy CSV preflight validator.

This module intentionally uses only the Python standard library so it can run
locally, in CI, or as an Azure Container Apps Job without cloud lock-in.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VALIDATOR_VERSION = "0.1.0"
DEFAULT_REQUIRED_FIELDS = ("genus", "species")
TAXON_RE = re.compile(r"^[A-Z][A-Za-z-]+(?:\s+[a-z][a-z-]+)?$")


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    row: int | None = None


@dataclass
class Report:
    source_filename: str
    source_sha256: str
    generated_at: str
    validator_version: str
    status: str
    encoding: str
    delimiter: str
    columns: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] | None = None
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [asdict(item) for item in self.findings]
        return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:4]
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    return "utf-8"


def normalize(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]], str, str]:
    encoding = detect_encoding(path)
    try:
        text = path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(f"unsupported or invalid text encoding: {exc}") from exc
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    columns = [normalize(c) for c in (reader.fieldnames or []) if normalize(c)]
    rows = [{normalize(k): normalize(v) for k, v in row.items() if k is not None} for row in reader]
    return columns, rows, encoding, delimiter


def first_present(row: dict[str, str], names: Iterable[str]) -> str:
    lookup = {key.casefold(): value for key, value in row.items()}
    for name in names:
        value = lookup.get(name.casefold(), "")
        if value:
            return value
    return ""


def taxon_key(row: dict[str, str]) -> str:
    identifier = first_present(row, ("taxon_id", "taxonid", "id", "ipni_id", "accepted_name_id"))
    if identifier:
        return f"id:{identifier.casefold()}"
    scientific = first_present(row, ("scientific_name", "scientificname", "taxon_name", "name"))
    if not scientific:
        genus = first_present(row, ("genus",))
        species = first_present(row, ("species", "specific_epithet", "specificepithet"))
        scientific = normalize(f"{genus} {species}")
    return f"name:{scientific.casefold()}"


def canonical_row(row: dict[str, str]) -> str:
    return json.dumps({k.casefold(): normalize(v) for k, v in sorted(row.items())}, sort_keys=True, ensure_ascii=False)


def compare_rows(candidate: list[dict[str, str]], baseline: list[dict[str, str]]) -> dict[str, Any]:
    current = {taxon_key(row): canonical_row(row) for row in candidate if taxon_key(row) != "name:"}
    previous = {taxon_key(row): canonical_row(row) for row in baseline if taxon_key(row) != "name:"}
    current_keys, previous_keys = set(current), set(previous)
    changed = sorted(key for key in current_keys & previous_keys if current[key] != previous[key])
    return {
        "added": len(current_keys - previous_keys),
        "removed": len(previous_keys - current_keys),
        "changed": len(changed),
        "unchanged": len((current_keys & previous_keys) - set(changed)),
        "candidate_unique_taxa": len(current_keys),
        "baseline_unique_taxa": len(previous_keys),
        "sample_added_keys": sorted(current_keys - previous_keys)[:25],
        "sample_removed_keys": sorted(previous_keys - current_keys)[:25],
        "sample_changed_keys": changed[:25],
    }


def validate(path: Path, baseline_path: Path | None = None, required_fields: tuple[str, ...] = DEFAULT_REQUIRED_FIELDS) -> Report:
    columns, rows, encoding, delimiter = load_csv(path)
    findings: list[Finding] = []
    folded_columns = {column.casefold() for column in columns}
    missing_required = [field for field in required_fields if field.casefold() not in folded_columns]
    if missing_required:
        findings.append(Finding("FAIL", "missing_required_columns", f"Missing required columns: {', '.join(missing_required)}"))

    keys: list[str] = []
    null_counts: Counter[str] = Counter()
    malformed_taxa = 0
    empty_identity = 0
    for index, row in enumerate(rows, start=2):
        for column in columns:
            if not normalize(row.get(column)):
                null_counts[column] += 1
        key = taxon_key(row)
        keys.append(key)
        if key == "name:":
            empty_identity += 1
            findings.append(Finding("FAIL", "missing_taxon_identity", "Row has no usable identifier or taxon name", index))
        scientific = first_present(row, ("scientific_name", "scientificname", "taxon_name", "name"))
        if not scientific:
            scientific = normalize(f"{first_present(row, ('genus',))} {first_present(row, ('species', 'specific_epithet', 'specificepithet'))}")
        if scientific and not TAXON_RE.match(scientific):
            malformed_taxa += 1
            findings.append(Finding("WARN", "malformed_taxon_name", f"Taxon name may be malformed: {scientific}", index))

    duplicate_counts = {key: count for key, count in Counter(keys).items() if key != "name:" and count > 1}
    if duplicate_counts:
        findings.append(Finding("WARN", "duplicate_taxa", f"Detected {len(duplicate_counts)} duplicated taxon keys"))
    if not rows:
        findings.append(Finding("FAIL", "empty_file", "CSV contains no data rows"))

    diff = None
    if baseline_path:
        _, baseline_rows, _, _ = load_csv(baseline_path)
        diff = compare_rows(rows, baseline_rows)

    status = "FAIL" if any(item.level == "FAIL" for item in findings) else "WARN" if findings else "PASS"
    return Report(
        source_filename=path.name,
        source_sha256=sha256_file(path),
        generated_at=datetime.now(timezone.utc).isoformat(),
        validator_version=VALIDATOR_VERSION,
        status=status,
        encoding=encoding,
        delimiter=delimiter,
        columns=columns,
        metrics={
            "row_count": len(rows),
            "column_count": len(columns),
            "duplicate_taxon_key_count": len(duplicate_counts),
            "duplicate_row_count": sum(duplicate_counts.values()),
            "missing_taxon_identity_count": empty_identity,
            "malformed_taxon_name_count": malformed_taxa,
            "null_counts": dict(sorted(null_counts.items())),
        },
        diff=diff,
        findings=findings,
    )


def write_human_summary(report: Report, output: Path) -> None:
    lines = [
        f"# Taxonomy Preflight: {report.status}",
        "",
        f"- Source: `{report.source_filename}`",
        f"- SHA-256: `{report.source_sha256}`",
        f"- Validator: `{report.validator_version}`",
        f"- Rows: {report.metrics['row_count']}",
        f"- Columns: {report.metrics['column_count']}",
        f"- Duplicate taxon keys: {report.metrics['duplicate_taxon_key_count']}",
        f"- Missing taxon identity: {report.metrics['missing_taxon_identity_count']}",
        f"- Malformed taxon names: {report.metrics['malformed_taxon_name_count']}",
    ]
    if report.diff:
        lines.extend(["", "## Baseline comparison", *[f"- {key}: {value}" for key, value in report.diff.items() if not key.startswith("sample_")]])
    lines.extend(["", "## Findings"])
    lines.extend(f"- **{item.level}** `{item.code}`{f' (row {item.row})' if item.row else ''}: {item.message}" for item in report.findings)
    if not report.findings:
        lines.append("- No findings.")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a taxonomy CSV without importing or publishing it.")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--json-output", type=Path, default=Path("taxonomy-preflight-report.json"))
    parser.add_argument("--summary-output", type=Path, default=Path("taxonomy-preflight-summary.md"))
    args = parser.parse_args()
    report = validate(args.candidate, args.baseline)
    args.json_output.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_human_summary(report, args.summary_output)
    print(json.dumps({"status": report.status, "report": str(args.json_output), "summary": str(args.summary_output)}))
    return 2 if report.status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
