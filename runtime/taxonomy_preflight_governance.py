"""Governed execution wrapper for the taxonomy preflight validator.

This module adds production-oriented controls without importing, publishing, or
mutating taxonomy data. It remains cloud-neutral and uses only the standard
library plus the sibling deterministic validator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.taxonomy_preflight import (
    REPORT_SCHEMA_VERSION,
    VALIDATOR_VERSION,
    Policy,
    atomic_write_text,
    sha256_file,
    validate,
    write_human_summary,
    write_manifest,
)

GOVERNANCE_VERSION = "0.1.0"
REQUIRED_REPORT_KEYS = {
    "report_schema_version",
    "run_id",
    "source_filename",
    "source_sha256",
    "generated_at",
    "validator_version",
    "status",
    "input_shape",
    "metrics",
    "findings",
}


@dataclass(frozen=True)
class GovernancePolicy:
    require_baseline: bool = False
    allowed_input_shapes: tuple[str, ...] = ("headered", "legacy_world_plants_headerless")
    allowed_suffixes: tuple[str, ...] = (".csv", ".tsv", ".txt")
    maximum_candidate_bytes: int = 250_000_000
    maximum_columns: int = 256
    maximum_overall_null_ratio: float = 0.95
    require_private_output_directory: bool = True

    @classmethod
    def from_path(cls, path: Path | None) -> "GovernancePolicy":
        if path is None:
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown governance policy fields: {', '.join(unknown)}")
        for key in ("allowed_input_shapes", "allowed_suffixes"):
            if key in payload:
                payload[key] = tuple(payload[key])
        policy = cls(**payload)
        if policy.maximum_candidate_bytes < 1 or policy.maximum_columns < 1:
            raise ValueError("governance size limits must be positive")
        if not 0 <= policy.maximum_overall_null_ratio <= 1:
            raise ValueError("maximum_overall_null_ratio must be between 0 and 1")
        if not policy.allowed_input_shapes or not policy.allowed_suffixes:
            raise ValueError("allowed input shapes and suffixes may not be empty")
        return policy


def deterministic_timestamp() -> str:
    """Use SOURCE_DATE_EPOCH when supplied, otherwise current UTC."""
    raw = os.getenv("SOURCE_DATE_EPOCH")
    if raw is not None:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("SOURCE_DATE_EPOCH must be an integer") from exc
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _directory_is_private(path: Path) -> bool:
    """Best-effort POSIX check; Windows is treated as not provably unsafe."""
    if os.name == "nt" or not path.exists():
        return True
    return (path.stat().st_mode & 0o077) == 0


def preflight_inputs(candidate: Path, baseline: Path | None, output_dir: Path, policy: GovernancePolicy) -> None:
    if not candidate.is_file():
        raise ValueError(f"candidate is not a regular file: {candidate}")
    if candidate.suffix.casefold() not in {item.casefold() for item in policy.allowed_suffixes}:
        raise ValueError(f"candidate suffix is not allowed: {candidate.suffix}")
    if candidate.stat().st_size > policy.maximum_candidate_bytes:
        raise ValueError(
            f"candidate size {candidate.stat().st_size} exceeds governance maximum {policy.maximum_candidate_bytes}"
        )
    if policy.require_baseline and baseline is None:
        raise ValueError("baseline is required by governance policy")
    if baseline is not None and not baseline.is_file():
        raise ValueError(f"baseline is not a regular file: {baseline}")
    if policy.require_private_output_directory and output_dir.exists() and not _directory_is_private(output_dir):
        raise ValueError(f"output directory permissions are too broad: {output_dir}")


def validate_report_contract(payload: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_REPORT_KEYS - set(payload))
    if missing:
        raise ValueError(f"report contract missing keys: {', '.join(missing)}")
    if payload["report_schema_version"] != REPORT_SCHEMA_VERSION:
        raise ValueError("unexpected report schema version")
    if payload["validator_version"] != VALIDATOR_VERSION:
        raise ValueError("unexpected validator version")
    if payload["status"] not in {"PASS", "WARN", "FAIL"}:
        raise ValueError("invalid report status")
    if not isinstance(payload["metrics"], dict) or not isinstance(payload["findings"], list):
        raise ValueError("report metrics/findings types are invalid")


def _overall_null_ratio(report_payload: dict[str, Any]) -> float:
    metrics = report_payload["metrics"]
    rows = max(int(metrics.get("row_count", 0)), 1)
    columns = max(int(metrics.get("column_count", 0)), 1)
    nulls = sum(int(value) for value in metrics.get("null_counts", {}).values())
    return nulls / (rows * columns)


def enforce_governance(report_payload: dict[str, Any], policy: GovernancePolicy) -> list[str]:
    violations: list[str] = []
    if report_payload["input_shape"] not in policy.allowed_input_shapes:
        violations.append(f"input shape not allowed: {report_payload['input_shape']}")
    column_count = int(report_payload["metrics"].get("column_count", 0))
    if column_count > policy.maximum_columns:
        violations.append(f"column count {column_count} exceeds {policy.maximum_columns}")
    null_ratio = _overall_null_ratio(report_payload)
    if null_ratio > policy.maximum_overall_null_ratio:
        violations.append(
            f"overall null ratio {null_ratio:.4%} exceeds {policy.maximum_overall_null_ratio:.4%}"
        )
    return violations


def _bundle_checksum(artifacts: dict[str, dict[str, str]]) -> str:
    canonical = json.dumps(artifacts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    receipt_path = bundle_dir / "receipt.json"
    if not manifest_path.is_file() or not receipt_path.is_file():
        raise ValueError("bundle is missing manifest.json or receipt.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", {})
    for name, metadata in artifacts.items():
        artifact_path = (bundle_dir / metadata["path"]).resolve()
        if bundle_dir.resolve() not in artifact_path.parents:
            raise ValueError(f"artifact escapes bundle directory: {name}")
        if not artifact_path.is_file():
            raise ValueError(f"artifact missing: {name}")
        if sha256_file(artifact_path) != metadata["sha256"]:
            raise ValueError(f"artifact checksum mismatch: {name}")
    expected = _bundle_checksum(artifacts)
    if receipt.get("bundle_checksum") != expected:
        raise ValueError("bundle receipt checksum mismatch")
    report_payload = json.loads((bundle_dir / "report.json").read_text(encoding="utf-8"))
    validate_report_contract(report_payload)
    return {"verified": True, "run_id": report_payload["run_id"], "bundle_checksum": expected}


def execute_bundle(
    candidate: Path,
    baseline: Path | None,
    output_dir: Path,
    validator_policy: Policy,
    governance_policy: GovernancePolicy,
) -> tuple[Path, dict[str, Any]]:
    preflight_inputs(candidate, baseline, output_dir, governance_policy)
    output_parent = output_dir.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_parent))
    try:
        report = validate(candidate, baseline, validator_policy)
        report_payload = report.to_dict()
        report_payload["generated_at"] = deterministic_timestamp()
        validate_report_contract(report_payload)
        violations = enforce_governance(report_payload, governance_policy)
        if violations:
            report_payload["status"] = "FAIL"
            report_payload.setdefault("findings", []).extend(
                {"level": "FAIL", "code": "governance_violation", "message": item, "row": None}
                for item in violations
            )

        report_path = staging / "report.json"
        summary_path = staging / "summary.md"
        manifest_path = staging / "manifest.json"
        atomic_write_text(report_path, json.dumps(report_payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        report.status = report_payload["status"]
        report.generated_at = report_payload["generated_at"]
        report.findings = [type(report.findings[0])(**item) if report.findings else item for item in report_payload["findings"]] if False else report.findings
        write_human_summary(report, summary_path)
        write_manifest(report, report_path, summary_path, manifest_path)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Store paths relative to the bundle so verification is relocation-safe.
        for metadata in manifest["artifacts"].values():
            metadata["path"] = Path(metadata["path"]).name
        atomic_write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        receipt = {
            "governance_version": GOVERNANCE_VERSION,
            "run_id": report_payload["run_id"],
            "status": report_payload["status"],
            "completed_at": report_payload["generated_at"],
            "candidate": {"filename": candidate.name, "sha256": report_payload["source_sha256"]},
            "baseline": None if baseline is None else {"filename": baseline.name, "sha256": report_payload["baseline_sha256"]},
            "governance_policy": asdict(governance_policy),
            "bundle_checksum": _bundle_checksum(manifest["artifacts"]),
            "publication_authorized": False,
            "database_mutation_authorized": False,
        }
        atomic_write_text(staging / "receipt.json", json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        verify_bundle(staging)
        if output_dir.exists():
            raise ValueError(f"refusing to replace existing output bundle: {output_dir}")
        os.replace(staging, output_dir)
        return output_dir, receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or verify a governed taxonomy preflight bundle.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("candidate", type=Path)
    run.add_argument("--baseline", type=Path)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--validator-policy", type=Path)
    run.add_argument("--governance-policy", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("bundle_dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = verify_bundle(args.bundle_dir)
        else:
            bundle, receipt = execute_bundle(
                args.candidate,
                args.baseline,
                args.output_dir,
                Policy.from_path(args.validator_policy),
                GovernancePolicy.from_path(args.governance_policy),
            )
            result = {"bundle": str(bundle), **receipt}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 2 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
