"""Reproducibility checks for governed taxonomy preflight bundles.

Runs the same candidate/baseline/policy inputs twice under a fixed timestamp and
proves that all governed evidence artifacts are byte-identical. This module does
not import, publish, deploy, or mutate taxonomy data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from runtime.taxonomy_preflight import Policy, sha256_file
from runtime.taxonomy_preflight_governance import GovernancePolicy
from runtime.taxonomy_preflight_release_gate import ReleaseGatePolicy, execute_release_bundle

ARTIFACTS = ("report.json", "summary.md", "manifest.json", "receipt.json", "COMPLETE.json")


def _digest_map(bundle: Path) -> dict[str, str]:
    missing = [name for name in ARTIFACTS if not (bundle / name).is_file()]
    if missing:
        raise ValueError(f"bundle missing reproducibility artifacts: {', '.join(missing)}")
    return {name: sha256_file(bundle / name) for name in ARTIFACTS}


def verify_reproducibility(
    candidate: Path,
    baseline: Path,
    validator_policy: Policy,
    governance_policy: GovernancePolicy,
    release_policy: ReleaseGatePolicy,
    review_reference: str,
    source_date_epoch: int = 0,
) -> dict[str, object]:
    previous_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    root = Path(tempfile.mkdtemp(prefix="taxonomy-reproducibility-"))
    try:
        first = root / "first"
        second = root / "second"
        execute_release_bundle(candidate, baseline, first, validator_policy, governance_policy, release_policy, review_reference)
        execute_release_bundle(candidate, baseline, second, validator_policy, governance_policy, release_policy, review_reference)
        first_digests = _digest_map(first)
        second_digests = _digest_map(second)
        mismatches = sorted(name for name in ARTIFACTS if first_digests[name] != second_digests[name])
        if mismatches:
            raise ValueError(f"non-deterministic artifacts: {', '.join(mismatches)}")
        aggregate = hashlib.sha256(
            json.dumps(first_digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        report = json.loads((first / "report.json").read_text(encoding="utf-8"))
        return {
            "reproducible": True,
            "run_id": report["run_id"],
            "source_date_epoch": source_date_epoch,
            "artifact_digests": first_digests,
            "aggregate_digest": aggregate,
            "publication_authorized": False,
            "database_mutation_authorized": False,
            "azure_resources_created": False,
        }
    finally:
        if previous_epoch is None:
            os.environ.pop("SOURCE_DATE_EPOCH", None)
        else:
            os.environ["SOURCE_DATE_EPOCH"] = previous_epoch
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove governed taxonomy evidence is reproducible.")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--validator-policy", type=Path, required=True)
    parser.add_argument("--governance-policy", type=Path, required=True)
    parser.add_argument("--release-policy", type=Path, required=True)
    parser.add_argument("--review-reference", required=True)
    parser.add_argument("--source-date-epoch", type=int, default=0)
    args = parser.parse_args()
    try:
        result = verify_reproducibility(
            args.candidate,
            args.baseline,
            Policy.from_path(args.validator_policy),
            GovernancePolicy.from_path(args.governance_policy),
            ReleaseGatePolicy.from_path(args.release_policy),
            args.review_reference,
            args.source_date_epoch,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"reproducible": False, "error": str(exc)}, sort_keys=True))
        return 4
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
