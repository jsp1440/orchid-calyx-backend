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
import os
import re
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALIDATOR_VERSION = "0.3.0"
REPORT_SCHEMA_VERSION = "1.0.0"
HEADER_TOKENS = {
    "taxon_id", "taxonid", "id", "scientific_name", "scientificname",
    "taxon_name", "name", "genus", "species", "specific_epithet",
    "specificepithet", "status", "rank",
}
LEGACY_WORLD_PLANTS_COLUMNS = (
    "record_type", "legacy_id", "scientific_name", "publication",
    "legacy_field_5", "distribution", "synonymy",
)
BINOMIAL_RE = re.compile(r"^[A-Z][A-Za-z-]+\s+(?:×\s*)?[a-z][a-z-]+")


@dataclass(frozen=True)
class Policy:
    minimum_rows: int = 1
    maximum_removed_ratio: float = 0.05
    maximum_changed_ratio: float = 0.25
    maximum_missing_identity_ratio: float = 0.001
    maximum_duplicate_key_ratio: float = 0.01
    finding_sample_limit: int = 100

    @classmethod
    def from_path(cls, path: Path | None) -> "Policy":
        if path is None:
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        allowed = {item.name for item in cls.__dataclass_fields__.values()}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown policy fields: {', '.join(unknown)}")
        policy = cls(**payload)
        if policy.minimum_rows < 0 or policy.finding_sample_limit < 1:
            raise ValueError("policy counts must be non-negative and sample limit must be positive")
        for value in (
            policy.maximum_removed_ratio,
            policy.maximum_changed_ratio,
            policy.maximum_missing_identity_ratio,
            policy.maximum_duplicate_key_ratio,
        ):
            if not 0 <= value <= 1:
                raise ValueError("policy ratios must be between 0 and 1")
        return policy


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    row: int | None = None


@dataclass
class Report:
    report_schema_version: str
    run_id: str
    source_filename: str
    source_sha256: str
    baseline_filename: str | None
    baseline_sha256: str | None
    generated_at: str
    validator_version: str
    status: str
    encoding: str
    delimiter: str
    columns: list[str]
    input_shape: str
    policy: dict[str, Any]
    metrics: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] | None = None
    findings: list[Finding] = field(default_factory=list)
    finding_counts: dict[str, int] = field(default_factory=dict)

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


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _detect_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        counts = {item: sample.count(item) for item in ("|", "\t", ",", ";")}
        return max(counts, key=counts.get) if max(counts.values(), default=0) else ","


def _looks_like_header(first_row: list[str]) -> bool:
    return bool({normalize(value).casefold() for value in first_row} & HEADER_TOKENS)


def _legacy_columns(width: int) -> list[str]:
    columns = list(LEGACY_WORLD_PLANTS_COLUMNS)
    if width > len(columns):
        columns.extend(f"legacy_field_{index}" for index in range(len(columns) + 1, width + 1))
    return columns[:width]


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]], str, str, str, int]:
    if not path.is_file():
        raise ValueError(f"input file does not exist or is not a regular file: {path}")
    encoding = detect_encoding(path)
    try:
        text = path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(f"unsupported or invalid text encoding: {exc}") from exc
    delimiter = _detect_delimiter(text)
    parsed = [row for row in csv.reader(text.splitlines(), delimiter=delimiter) if any(normalize(v) for v in row)]
    if not parsed:
        return [], [], encoding, delimiter, "empty", 0

    widths = Counter(len(row) for row in parsed)
    expected_width = widths.most_common(1)[0][0]
    width_anomalies = sum(count for width, count in widths.items() if width != expected_width)
    if _looks_like_header(parsed[0]):
        columns = [normalize(value) or f"unnamed_{index}" for index, value in enumerate(parsed[0], start=1)]
        data_rows, input_shape = parsed[1:], "headered"
    elif delimiter == "|" and len(parsed[0]) >= 3:
        columns = _legacy_columns(max(len(row) for row in parsed))
        data_rows, input_shape = parsed, "legacy_world_plants_headerless"
    else:
        columns = [f"column_{index}" for index in range(1, max(len(row) for row in parsed) + 1)]
        data_rows, input_shape = parsed, "headerless_unknown"

    rows = []
    for raw in data_rows:
        padded = raw + [""] * (len(columns) - len(raw))
        rows.append({column: normalize(value) for column, value in zip(columns, padded)})
    return columns, rows, encoding, delimiter, input_shape, width_anomalies


def first_present(row: dict[str, str], names: Iterable[str]) -> str:
    lookup = {key.casefold(): value for key, value in row.items()}
    for name in names:
        if value := lookup.get(name.casefold(), ""):
            return value
    return ""


def scientific_name(row: dict[str, str]) -> str:
    direct = first_present(row, ("scientific_name", "scientificname", "taxon_name", "name"))
    if direct:
        return direct
    return normalize(f"{first_present(row, ('genus',))} {first_present(row, ('species', 'specific_epithet', 'specificepithet'))}")


def taxon_key(row: dict[str, str]) -> str:
    identifier = first_present(row, ("taxon_id", "taxonid", "id", "ipni_id", "accepted_name_id", "legacy_id"))
    return f"id:{identifier.casefold()}" if identifier else f"name:{scientific_name(row).casefold()}"


def canonical_row(row: dict[str, str]) -> str:
    return json.dumps({k.casefold(): normalize(v) for k, v in sorted(row.items())}, sort_keys=True, ensure_ascii=False)


def compare_rows(candidate: list[dict[str, str]], baseline: list[dict[str, str]]) -> dict[str, Any]:
    current = {taxon_key(row): canonical_row(row) for row in candidate if taxon_key(row) != "name:"}
    previous = {taxon_key(row): canonical_row(row) for row in baseline if taxon_key(row) != "name:"}
    current_keys, previous_keys = set(current), set(previous)
    changed = sorted(key for key in current_keys & previous_keys if current[key] != previous[key])
    baseline_count = max(len(previous_keys), 1)
    return {
        "added": len(current_keys - previous_keys),
        "removed": len(previous_keys - current_keys),
        "changed": len(changed),
        "unchanged": len((current_keys & previous_keys) - set(changed)),
        "candidate_unique_taxa": len(current_keys),
        "baseline_unique_taxa": len(previous_keys),
        "removed_ratio": len(previous_keys - current_keys) / baseline_count,
        "changed_ratio": len(changed) / baseline_count,
        "sample_added_keys": sorted(current_keys - previous_keys)[:25],
        "sample_removed_keys": sorted(previous_keys - current_keys)[:25],
        "sample_changed_keys": changed[:25],
    }


def _has_identity_columns(columns: list[str]) -> bool:
    folded = {column.casefold() for column in columns}
    return bool(folded & {"scientific_name", "scientificname", "taxon_name", "name"}) or (
        "genus" in folded and bool(folded & {"species", "specific_epithet", "specificepithet"})
    )


def _run_id(source_sha: str, baseline_sha: str | None, policy: Policy) -> str:
    payload = json.dumps({"source": source_sha, "baseline": baseline_sha, "policy": asdict(policy), "validator": VALIDATOR_VERSION}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def validate(path: Path, baseline_path: Path | None = None, policy: Policy | None = None) -> Report:
    policy = policy or Policy()
    columns, rows, encoding, delimiter, input_shape, width_anomalies = load_csv(path)
    source_sha = sha256_file(path)
    baseline_sha = sha256_file(baseline_path) if baseline_path else None
    findings: list[Finding] = []
    finding_totals: Counter[str] = Counter()

    def add(level: str, code: str, message: str, row: int | None = None) -> None:
        finding_totals[f"{level}:{code}"] += 1
        if sum(1 for item in findings if item.code == code) < policy.finding_sample_limit:
            findings.append(Finding(level, code, message, row))

    if input_shape == "headerless_unknown":
        add("FAIL", "unknown_headerless_shape", "Headerless file is not a recognized World Plants pipe export")
    if columns and not _has_identity_columns(columns):
        add("FAIL", "missing_taxon_identity_columns", "Expected scientific_name or genus plus species columns")
    if len(rows) < policy.minimum_rows:
        add("FAIL", "below_minimum_rows", f"Row count {len(rows)} is below policy minimum {policy.minimum_rows}")

    keys: list[str] = []
    null_counts: Counter[str] = Counter()
    record_types: Counter[str] = Counter()
    malformed_taxa = empty_identity = 0
    for index, row in enumerate(rows, start=1 if input_shape.startswith("legacy_") else 2):
        for column in columns:
            if not normalize(row.get(column)):
                null_counts[column] += 1
        record_types[first_present(row, ("record_type", "rank")) or "unspecified"] += 1
        key = taxon_key(row)
        keys.append(key)
        if key == "name:":
            empty_identity += 1
            add("FAIL", "missing_taxon_identity", "Row has no usable identifier or taxon name", index)
        name = scientific_name(row)
        record_type = first_present(row, ("record_type", "rank"))
        species_like = record_type.casefold() in {"s", "species", "subspecies", "variety", "form"} or not record_type
        if name and species_like and not BINOMIAL_RE.match(name):
            malformed_taxa += 1
            add("WARN", "malformed_taxon_name", f"Taxon name may be malformed: {name}", index)

    duplicates = {key: count for key, count in Counter(keys).items() if key != "name:" and count > 1}
    row_denominator = max(len(rows), 1)
    missing_ratio = empty_identity / row_denominator
    duplicate_ratio = len(duplicates) / row_denominator
    if duplicates:
        add("WARN", "duplicate_taxa", f"Detected {len(duplicates)} duplicated taxon keys")
    if missing_ratio > policy.maximum_missing_identity_ratio:
        add("FAIL", "missing_identity_ratio_exceeded", f"Missing identity ratio {missing_ratio:.4%} exceeds {policy.maximum_missing_identity_ratio:.4%}")
    if duplicate_ratio > policy.maximum_duplicate_key_ratio:
        add("FAIL", "duplicate_ratio_exceeded", f"Duplicate-key ratio {duplicate_ratio:.4%} exceeds {policy.maximum_duplicate_key_ratio:.4%}")
    if width_anomalies:
        add("WARN", "row_width_anomalies", f"Detected {width_anomalies} rows with non-modal field counts")
    if not rows:
        add("FAIL", "empty_file", "File contains no data rows")

    diff = None
    if baseline_path:
        _, baseline_rows, _, _, _, _ = load_csv(baseline_path)
        diff = compare_rows(rows, baseline_rows)
        if diff["removed_ratio"] > policy.maximum_removed_ratio:
            add("FAIL", "removed_ratio_exceeded", f"Removed ratio {diff['removed_ratio']:.4%} exceeds {policy.maximum_removed_ratio:.4%}")
        if diff["changed_ratio"] > policy.maximum_changed_ratio:
            add("FAIL", "changed_ratio_exceeded", f"Changed ratio {diff['changed_ratio']:.4%} exceeds {policy.maximum_changed_ratio:.4%}")

    status = "FAIL" if any(item.level == "FAIL" for item in findings) else "WARN" if findings else "PASS"
    return Report(
        report_schema_version=REPORT_SCHEMA_VERSION,
        run_id=_run_id(source_sha, baseline_sha, policy),
        source_filename=path.name,
        source_sha256=source_sha,
        baseline_filename=baseline_path.name if baseline_path else None,
        baseline_sha256=baseline_sha,
        generated_at=datetime.now(timezone.utc).isoformat(),
        validator_version=VALIDATOR_VERSION,
        status=status,
        encoding=encoding,
        delimiter=delimiter,
        columns=columns,
        input_shape=input_shape,
        policy=asdict(policy),
        metrics={
            "row_count": len(rows), "column_count": len(columns),
            "duplicate_taxon_key_count": len(duplicates), "duplicate_row_count": sum(duplicates.values()),
            "duplicate_key_ratio": duplicate_ratio, "missing_taxon_identity_count": empty_identity,
            "missing_taxon_identity_ratio": missing_ratio, "malformed_taxon_name_count": malformed_taxa,
            "row_width_anomaly_count": width_anomalies, "record_type_counts": dict(sorted(record_types.items())),
            "null_counts": dict(sorted(null_counts.items())),
        },
        diff=diff, findings=findings, finding_counts=dict(sorted(finding_totals.items())),
    )


def write_human_summary(report: Report, output: Path) -> None:
    lines = [
        f"# Taxonomy Preflight: {report.status}", "", f"- Run ID: `{report.run_id}`",
        f"- Report schema: `{report.report_schema_version}`", f"- Source: `{report.source_filename}`",
        f"- SHA-256: `{report.source_sha256}`", f"- Baseline: `{report.baseline_filename or 'none'}`",
        f"- Validator: `{report.validator_version}`", f"- Input shape: `{report.input_shape}`",
        f"- Rows: {report.metrics['row_count']}", f"- Columns: {report.metrics['column_count']}",
        f"- Duplicate taxon keys: {report.metrics['duplicate_taxon_key_count']}",
        f"- Missing taxon identity: {report.metrics['missing_taxon_identity_count']}",
        f"- Malformed taxon names: {report.metrics['malformed_taxon_name_count']}",
    ]
    if report.diff:
        lines.extend(["", "## Baseline comparison", *[f"- {key}: {value}" for key, value in report.diff.items() if not key.startswith("sample_")]])
    lines.extend(["", "## Finding totals"])
    lines.extend(f"- `{key}`: {value}" for key, value in report.finding_counts.items())
    lines.extend(["", "## Sampled findings"])
    lines.extend(f"- **{item.level}** `{item.code}`{f' (row {item.row})' if item.row else ''}: {item.message}" for item in report.findings)
    if not report.findings:
        lines.append("- No findings.")
    atomic_write_text(output, "\n".join(lines) + "\n")


def write_manifest(report: Report, report_path: Path, summary_path: Path, output: Path) -> None:
    manifest = {
        "run_id": report.run_id, "status": report.status, "validator_version": report.validator_version,
        "source_sha256": report.source_sha256, "baseline_sha256": report.baseline_sha256,
        "artifacts": {
            "report": {"path": str(report_path), "sha256": sha256_file(report_path)},
            "summary": {"path": str(summary_path), "sha256": sha256_file(summary_path)},
        },
    }
    atomic_write_text(output, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a taxonomy file without importing or publishing it.")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--json-output", type=Path, default=Path("taxonomy-preflight-report.json"))
    parser.add_argument("--summary-output", type=Path, default=Path("taxonomy-preflight-summary.md"))
    parser.add_argument("--manifest-output", type=Path, default=Path("taxonomy-preflight-manifest.json"))
    args = parser.parse_args()
    try:
        report = validate(args.candidate, args.baseline, Policy.from_path(args.policy))
        atomic_write_text(args.json_output, json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        write_human_summary(report, args.summary_output)
        write_manifest(report, args.json_output, args.summary_output, args.manifest_output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}))
        return 3
    print(json.dumps({"status": report.status, "run_id": report.run_id, "report": str(args.json_output), "summary": str(args.summary_output), "manifest": str(args.manifest_output)}))
    return 2 if report.status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
