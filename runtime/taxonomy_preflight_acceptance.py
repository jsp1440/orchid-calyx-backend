"""Build a review-only acceptance packet for AZURE-001 taxonomy preflight.

The packet consolidates release-bundle integrity, readiness evidence, and
reproducibility evidence. It never authorizes Azure provisioning, taxonomy
publication, database mutation, or production migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.taxonomy_preflight import atomic_write_text
from runtime.taxonomy_preflight_release_gate import ReleaseGatePolicy, verify_release_bundle

ACCEPTANCE_VERSION = "0.1.0"


@dataclass(frozen=True)
class AcceptancePacket:
    version: str
    decision: str
    run_id: str | None
    reasons: tuple[str, ...]
    release_bundle_verified: bool
    readiness_decision: str | None
    reproducibility_verified: bool
    aggregate_digest: str | None
    evidence_digest: str | None
    azure_provisioning_authorized: bool = False
    taxonomy_publication_authorized: bool = False
    database_mutation_authorized: bool = False
    production_migration_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _evidence_digest(parts: dict[str, Any]) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_acceptance(
    bundle_dir: Path,
    readiness_path: Path,
    reproducibility_path: Path,
    release_policy: ReleaseGatePolicy | None = None,
) -> AcceptancePacket:
    reasons: list[str] = []
    run_id: str | None = None
    release_verified = False
    readiness_decision: str | None = None
    reproducibility_verified = False
    aggregate_digest: str | None = None

    try:
        release = verify_release_bundle(bundle_dir, release_policy or ReleaseGatePolicy())
        release_verified = bool(release.get("release_verified"))
        run_id = str(release.get("run_id")) if release.get("run_id") else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reasons.append(f"release bundle verification failed: {exc}")

    try:
        readiness = _load_json(readiness_path, "readiness evidence")
        readiness_decision = str(readiness.get("decision")) if readiness.get("decision") else None
        if readiness.get("run_id") != run_id:
            reasons.append("readiness run_id does not match release bundle")
        if readiness_decision != "READY_FOR_REVIEW":
            reasons.append(f"readiness decision is {readiness_decision or 'missing'}")
        for key in (
            "azure_provisioning_authorized",
            "taxonomy_publication_authorized",
            "database_mutation_authorized",
        ):
            if readiness.get(key) is not False:
                reasons.append(f"readiness safety flag is unsafe or missing: {key}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reasons.append(f"readiness evidence invalid: {exc}")
        readiness = {}

    try:
        reproducibility = _load_json(reproducibility_path, "reproducibility evidence")
        reproducibility_verified = reproducibility.get("reproducible") is True
        aggregate_digest = reproducibility.get("aggregate_digest")
        if not reproducibility_verified:
            reasons.append("reproducibility evidence is not verified")
        if reproducibility.get("run_id") != run_id:
            reasons.append("reproducibility run_id does not match release bundle")
        if not isinstance(aggregate_digest, str) or len(aggregate_digest) != 64:
            reasons.append("reproducibility aggregate digest is missing or invalid")
        for key in (
            "azure_resources_created",
            "publication_authorized",
            "database_mutation_authorized",
        ):
            if reproducibility.get(key) is not False:
                reasons.append(f"reproducibility safety flag is unsafe or missing: {key}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reasons.append(f"reproducibility evidence invalid: {exc}")
        reproducibility = {}

    hard_failure = not release_verified or any(
        reason.startswith((
            "release bundle verification failed",
            "readiness evidence invalid",
            "reproducibility evidence invalid",
        ))
        for reason in reasons
    )
    decision = "BLOCK" if hard_failure else "REVIEW_ONLY" if reasons else "ACCEPTANCE_REVIEW_ONLY"
    digest = _evidence_digest({
        "run_id": run_id,
        "release_verified": release_verified,
        "readiness": readiness,
        "reproducibility": reproducibility,
    })
    return AcceptancePacket(
        ACCEPTANCE_VERSION,
        decision,
        run_id,
        tuple(reasons),
        release_verified,
        readiness_decision,
        reproducibility_verified,
        aggregate_digest if isinstance(aggregate_digest, str) else None,
        digest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a non-authorizing AZURE-001 acceptance packet.")
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--reproducibility", type=Path, required=True)
    parser.add_argument("--release-policy", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        packet = evaluate_acceptance(
            args.bundle_dir,
            args.readiness,
            args.reproducibility,
            ReleaseGatePolicy.from_path(args.release_policy),
        )
        payload = json.dumps(packet.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.output:
            atomic_write_text(args.output, payload)
        print(payload, end="")
        return 0 if packet.decision == "ACCEPTANCE_REVIEW_ONLY" else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"decision": "BLOCK", "error": str(exc)}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
