"""Release gate for governed taxonomy preflight bundles.

This layer adds operator review metadata, concurrency protection, symlink/path
safety, bundle size limits, completion markers, and a non-provisioning Azure
execution specification. It never imports, publishes, or mutates taxonomy data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from runtime.taxonomy_preflight import Policy, atomic_write_text, sha256_file
from runtime.taxonomy_preflight_governance import (
    GovernancePolicy,
    execute_bundle,
    verify_bundle,
)

RELEASE_GATE_VERSION = "0.1.0"


@dataclass(frozen=True)
class ReleaseGatePolicy:
    require_review_reference: bool = True
    reject_symlinks: bool = True
    maximum_bundle_bytes: int = 25_000_000
    require_safety_flags: bool = True
    require_policy_hashes: bool = True
    require_complete_marker: bool = True

    @classmethod
    def from_path(cls, path: Path | None) -> "ReleaseGatePolicy":
        if path is None:
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        unknown = sorted(set(payload) - set(cls.__dataclass_fields__))
        if unknown:
            raise ValueError(f"unknown release-gate policy fields: {', '.join(unknown)}")
        policy = cls(**payload)
        if policy.maximum_bundle_bytes < 1:
            raise ValueError("maximum_bundle_bytes must be positive")
        return policy


def _json_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_or_default_hash(path: Path | None, payload: dict[str, Any]) -> str:
    return sha256_file(path) if path else _json_sha256(payload)


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symbolic link: {path}")


def _validate_paths(candidate: Path, baseline: Path | None, output_dir: Path, policy: ReleaseGatePolicy) -> None:
    if policy.reject_symlinks:
        _reject_symlink(candidate, "candidate")
        if baseline is not None:
            _reject_symlink(baseline, "baseline")
        if output_dir.exists():
            _reject_symlink(output_dir, "output directory")
    resolved_output = output_dir.resolve()
    if resolved_output == candidate.resolve() or (baseline and resolved_output == baseline.resolve()):
        raise ValueError("output directory may not replace an input file")


@contextmanager
def output_lock(output_dir: Path) -> Iterator[None]:
    """Prevent concurrent writers targeting the same governed bundle."""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"another release-gate operation is active: {lock_path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("utf-8"))
        os.close(descriptor)
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def plan_release(
    candidate: Path,
    baseline: Path | None,
    output_dir: Path,
    review_reference: str | None,
    validator_policy: Policy,
    governance_policy: GovernancePolicy,
    release_policy: ReleaseGatePolicy,
) -> dict[str, Any]:
    """Return a deterministic plan without creating a bundle or Azure resource."""
    _validate_paths(candidate, baseline, output_dir, release_policy)
    if release_policy.require_review_reference and not (review_reference or "").strip():
        raise ValueError("review reference is required by release-gate policy")
    if not candidate.is_file():
        raise ValueError(f"candidate is not a regular file: {candidate}")
    if baseline is not None and not baseline.is_file():
        raise ValueError(f"baseline is not a regular file: {baseline}")
    return {
        "release_gate_version": RELEASE_GATE_VERSION,
        "mode": "plan_only",
        "candidate": {"filename": candidate.name, "sha256": sha256_file(candidate), "bytes": candidate.stat().st_size},
        "baseline": None if baseline is None else {"filename": baseline.name, "sha256": sha256_file(baseline), "bytes": baseline.stat().st_size},
        "output_dir": str(output_dir),
        "review_reference": review_reference,
        "validator_policy_sha256": _json_sha256(asdict(validator_policy)),
        "governance_policy_sha256": _json_sha256(asdict(governance_policy)),
        "release_policy_sha256": _json_sha256(asdict(release_policy)),
        "azure_resources_created": False,
        "database_mutation_authorized": False,
        "publication_authorized": False,
    }


def _bundle_size(bundle_dir: Path) -> int:
    return sum(path.stat().st_size for path in bundle_dir.rglob("*") if path.is_file())


def execute_release(
    candidate: Path,
    baseline: Path | None,
    output_dir: Path,
    review_reference: str | None,
    validator_policy: Policy,
    governance_policy: GovernancePolicy,
    release_policy: ReleaseGatePolicy,
    validator_policy_path: Path | None = None,
    governance_policy_path: Path | None = None,
    release_policy_path: Path | None = None,
) -> dict[str, Any]:
    plan = plan_release(
        candidate, baseline, output_dir, review_reference,
        validator_policy, governance_policy, release_policy,
    )
    with output_lock(output_dir):
        bundle, _ = execute_bundle(candidate, baseline, output_dir, validator_policy, governance_policy)
        receipt_path = bundle / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt.update({
            "release_gate_version": RELEASE_GATE_VERSION,
            "review_reference": review_reference,
            "validator_policy_sha256": _file_or_default_hash(validator_policy_path, asdict(validator_policy)),
            "governance_policy_sha256": _file_or_default_hash(governance_policy_path, asdict(governance_policy)),
            "release_policy_sha256": _file_or_default_hash(release_policy_path, asdict(release_policy)),
            "azure_resources_created": False,
        })
        atomic_write_text(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        total_bytes = _bundle_size(bundle)
        if total_bytes > release_policy.maximum_bundle_bytes:
            raise ValueError(f"bundle size {total_bytes} exceeds {release_policy.maximum_bundle_bytes}")
        complete_payload = {
            "run_id": receipt["run_id"],
            "status": receipt["status"],
            "bundle_bytes": total_bytes,
            "receipt_sha256": sha256_file(receipt_path),
        }
        atomic_write_text(bundle / "COMPLETE.json", json.dumps(complete_payload, indent=2, sort_keys=True) + "\n")
        result = verify_release_bundle(bundle, release_policy)
        return {**plan, **result, "mode": "executed"}


def verify_release_bundle(bundle_dir: Path, policy: ReleaseGatePolicy) -> dict[str, Any]:
    base = verify_bundle(bundle_dir)
    receipt_path = bundle_dir / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((bundle_dir / "report.json").read_text(encoding="utf-8"))
    if manifest.get("run_id") != report.get("run_id") or receipt.get("run_id") != report.get("run_id"):
        raise ValueError("run_id mismatch across report, manifest, and receipt")
    if manifest.get("status") != report.get("status") or receipt.get("status") != report.get("status"):
        raise ValueError("status mismatch across report, manifest, and receipt")
    if policy.require_safety_flags:
        for key in ("publication_authorized", "database_mutation_authorized", "azure_resources_created"):
            if receipt.get(key) is not False:
                raise ValueError(f"unsafe or missing receipt flag: {key}")
    if policy.require_policy_hashes:
        for key in ("validator_policy_sha256", "governance_policy_sha256", "release_policy_sha256"):
            value = receipt.get(key, "")
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"missing or invalid policy hash: {key}")
    complete_path = bundle_dir / "COMPLETE.json"
    if policy.require_complete_marker and not complete_path.is_file():
        raise ValueError("bundle is missing COMPLETE.json")
    if complete_path.is_file():
        complete = json.loads(complete_path.read_text(encoding="utf-8"))
        if complete.get("run_id") != report.get("run_id"):
            raise ValueError("completion marker run_id mismatch")
        if complete.get("receipt_sha256") != sha256_file(receipt_path):
            raise ValueError("completion marker receipt checksum mismatch")
    total_bytes = _bundle_size(bundle_dir)
    if total_bytes > policy.maximum_bundle_bytes:
        raise ValueError(f"bundle size {total_bytes} exceeds {policy.maximum_bundle_bytes}")
    return {**base, "release_verified": True, "bundle_bytes": total_bytes}


def azure_execution_spec(
    image: str,
    resource_group: str = "rg-oc-taxonomy-pilot-westus2",
    location: str = "westus2",
) -> dict[str, Any]:
    """Generate a reviewable specification only; it does not provision Azure."""
    if not image or "@sha256:" not in image:
        raise ValueError("container image must be pinned by sha256 digest")
    return {
        "spec_version": "1.0.0",
        "provision": False,
        "service": "Azure Container Apps Job",
        "resource_group": resource_group,
        "location": location,
        "trigger": "manual",
        "replica_timeout_seconds": 1800,
        "replica_retry_limit": 0,
        "parallelism": 1,
        "replica_completion_count": 1,
        "scale_to_zero": True,
        "public_ingress": False,
        "image": image,
        "identity": "managed_identity_required",
        "storage": "private_blob_required",
        "database_access": False,
        "publication_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan, run, or verify a taxonomy release-gate bundle.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        command.add_argument("candidate", type=Path)
        command.add_argument("--baseline", type=Path)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--review-reference")
        command.add_argument("--validator-policy", type=Path)
        command.add_argument("--governance-policy", type=Path)
        command.add_argument("--release-policy", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("bundle_dir", type=Path)
    verify.add_argument("--release-policy", type=Path)
    spec = sub.add_parser("azure-spec")
    spec.add_argument("--image", required=True)
    spec.add_argument("--resource-group", default="rg-oc-taxonomy-pilot-westus2")
    spec.add_argument("--location", default="westus2")
    args = parser.parse_args()
    try:
        if args.command == "azure-spec":
            result = azure_execution_spec(args.image, args.resource_group, args.location)
        elif args.command == "verify":
            result = verify_release_bundle(args.bundle_dir, ReleaseGatePolicy.from_path(args.release_policy))
        else:
            validator_policy = Policy.from_path(args.validator_policy)
            governance_policy = GovernancePolicy.from_path(args.governance_policy)
            release_policy = ReleaseGatePolicy.from_path(args.release_policy)
            if args.command == "plan":
                result = plan_release(args.candidate, args.baseline, args.output_dir, args.review_reference, validator_policy, governance_policy, release_policy)
            else:
                result = execute_release(
                    args.candidate, args.baseline, args.output_dir, args.review_reference,
                    validator_policy, governance_policy, release_policy,
                    args.validator_policy, args.governance_policy, args.release_policy,
                )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
