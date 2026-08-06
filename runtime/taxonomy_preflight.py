"""Deterministic, non-publishing taxonomy file preflight validator.

Supports ordinary headered CSV/TSV files and the legacy headerless, pipe-delimited
World Plants/World Orchids export shape used by Orchid Continuum. The module uses
only the Python standard library and never imports or publishes taxonomy data.
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

VALIDATOR_VERSION = "0.2.0"
HEADER_TOKENS = {
    "taxon_id", "taxonid", "id", "scientific_name", "scientificname",
    "taxon_name", "name", "genus", "species", "specific_epithet",
    "specificepithet", "status", "rank",
}
# Historical World Plants exports observed in Orchid Continuum use pipes and put
# the full taxon string in the third field: S||Maxillaria ...|publication|...
LEGACY_WORLD_PLANTS_COLUMNS = (
    "record_type", "legacy_id", "scientific_name", "publication",
    "legacy_field_5", "distribution", "synonymy",
)
BINOMIAL_RE = re.compile(r"^[A-Z][A-Za-z-]+\s+(?:×\s*)?[a-z][a-z-]+")


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
    input_shape: str
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


def _detect_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        counts = {item: sample.count(item) for item in ("|", "\t", ",", ";")}
        return max(counts, key=counts.get) if max(counts.values(), default=0) else ","


def _looks_like_header(first_row: list[str]) -> bool:
    folded = {normalize(value).casefold() for value in first_row}
    return bool(folded & HEADER_TOKENS)


def _legacy_columns(width: int) -> list[str]:
    columns = list(LEGACY_WORLD_PLANTS_COLUMNS)
    if width > len(columns):
        columns.extend(f"legacy_field_{index}" for index in range(len(columns) + 1, width + 1))
    return columns[:width]


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]], str, str, str]:
    encoding = detect_encoding(path)
    try:
        text = path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(f"unsupported or invalid text encoding: {exc}") from exc
    delimiter = _detect_delimiter(text)
    parsed = list(csv.reader(text.splitlines(), delimiter=delimiter))
    parsed = [row for row in parsed if any(normalize(value) for value in row)]
    if not parsed:
        return [], [], encoding, delimiter, "empty"

    if _looks_like_header(parsed[0]):
        columns = [normalize(value) or f"unnamed_{index}" for index, value in enumerate(parsed[0], start=1)]
        data_rows = parsed[1:]
        input_shape = "headered"
    elif delimiter == "|" and len(parsed[0]) >= 3:
        width = max(len(row) for row in parsed)
        columns = _legacy_columns(width)
        data_rows = parsed
        input_shape = "legacy_world_plants_headerless"
    else:
        width = max(len(row) for row in parsed)
        columns = [f"column_{index}" for index in range(1, width + 1)]
        data_rows = parsed
        input_shape = "headerless_unknown"

    rows: list[dict[str, str]] = []
    for raw in data_rows:
        padded = raw + [""] * (len(columns) - len(raw))
        rows.append({column: normalize(value) for column, value in zip(columns, padded)})
    return columns, rows, encoding, delimiter, input_shape


def first_present(row: dict[str, str], names: Iterable[str]) -> str:
    lookup = {key.casefold(): value for key, value in row.items()}
    for name in names:
        value = lookup.get(name.casefold(), "")
        if value:
            return value
    return ""


def scientific_name(row: dict[str, str]) -> str:
    direct = first_present(row, ("scientific_name", "scientificname", "taxon_name", "name"))
    if direct:
        return direct
    genus = first_present(row, ("genus",))
    species = first_present(row, ("species", "specific_epithet", "specificepithet"))
    return normalize(f"{genus} {species}")


def taxon_key(row: dict[str, str]) -> str:
    identifier = first_present(row, ("taxon_id", "taxonid", "id", "ipni_id", "accepted_name_id", "legacy_id"))
    if identifier:
        return f"id:{identifier.casefold()}"
    return f"name:{scientific_name(row).casefold()}"


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


def _has_identity_columns(columns: list[str]) -> bool:
    folded = {column.casefold() for column in columns}
    direct = bool(folded & {"scientific_name", "scientificname", "taxon_name", "name"})
    split = "genus" in folded and bool(folded & {"species", "specific_epithet", "specificepithet"})
    return direct or split


def validate(path: Path, baseline_path: Path | None = None) -> Report:
    columns, rows, encoding, delimiter, input_shape = load_csv(path)
    findings: list[Finding] = []
    if input_shape == "headerless_unknown":
        findings.append(Finding("FAIL", "unknown_headerless_shape", "Headerless file is not a recognized World Plants pipe export"))
    if columns and not _has_identity_columns(columns):
        findings.append(Finding("FAIL", "missing_taxon_identity_columns", "Expected scientific_name or genus plus species columns"))

    keys: list[str] = []
    null_counts: Counter[str] = Counter()
    malformed_taxa = 0
    empty_identity = 0
    row_width_anomalies = 0
    for index, row in enumerate(rows, start=1 if input_shape.startswith("legacy_") else 2):
        for column in columns:
            if not normalize(row.get(column)):
                null_counts[column] += 1
        key = taxon_key(row)
        keys.append(key)
        if key == "name:":
            empty_identity += 1
            findings.append(Finding("FAIL", "missing_taxon_identity", "Row has no usable identifier or taxon name", index))
        name = scientific_name(row)
        record_type = first_present(row, ("record_type", "rank"))
        species_like = record_type.casefold() in {"s", "species", "subspecies", "variety", "form"} or not record_type
        if name and species_like and not BINOMIAL_RE.match(name):
            malformed_taxa += 1
            if malformed_taxa <= 100:
                findings.append(Finding("WARN", "malformed_taxon_name", f"Taxon name may be malformed: {name}", index))
        if any(key.startswith("unnamed_") for key in row):
            row_width_anomalies += 1

    duplicate_counts = {key: count for key, count in Counter(keys).items() if key != "name:" and count > 1}
    if duplicate_counts:
        findings.append(Finding("WARN", "duplicate_taxa", f"Detected {len(duplicate_counts)} duplicated taxon keys"))
    if malformed_taxa > 100:
        findings.append(Finding("WARN", "malformed_taxon_findings_truncated", f"Only the first 100 of {malformed_taxa} malformed-name findings are listed"))
    if not rows:
        findings.append(Finding("FAIL", "empty_file", "File contains no data rows"))

    diff = None
    if baseline_path:
        _, baseline_rows, _, _, _ = load_csv(baseline_path)
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
        input_shape=input_shape,
        metrics={
            "row_count": len(rows),
            "column_count": len(columns),
            "duplicate_taxon_key_count": len(duplicate_counts),
            "duplicate_row_count": sum(duplicate_counts.values()),
            "missing_taxon_identity_count": empty_identity,
            "malformed_taxon_name_count": malformed_taxa,
            "row_width_anomaly_count": row_width_anomalies,
            "null_counts": dict(sorted(null_counts.items())),
        },
        diff=diff,
        findings=findings,
    )


def write_human_summary(report: Report, output: Path) -> None:
    lines = [
        f"# Taxonomy Preflight: {report.status}", "",
        f"- Source: `{report.source_filename}`",
        f"- SHA-256: `{report.source_sha256}`",
        f"- Validator: `{report.validator_version}`",
        f"- Input shape: `{report.input_shape}`",
        f"- Delimiter: `{report.delimiter}`",
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
    parser = argparse.ArgumentParser(description="Validate a taxonomy file without importing or publishing it.")
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
