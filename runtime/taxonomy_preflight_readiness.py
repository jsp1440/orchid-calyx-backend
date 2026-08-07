"""Evaluate taxonomy-preflight evidence without authorizing deployment or publication."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runtime.taxonomy_preflight_attestations import load_and_evaluate
from runtime.taxonomy_preflight_governance import verify_bundle

READINESS_VERSION = "0.2.0"


@dataclass(frozen=True)
class ReadinessDecision:
    version: str
    decision: str
    reasons: tuple[str, ...]
    run_id: str | None
    ci_validated: bool
    real_dataset_validated: bool
    billing_credit_verified: bool
    budget_alerts_configured: bool
    microsoft_review_complete: bool
    evidence_mode: str
    evidence_digest: str | None
    azure_provisioning_authorized: bool = False
    taxonomy_publication_authorized: bool = False
    database_mutation_authorized: bool = False
    production_migration_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate(
    bundle_dir: Path,
    *,
    ci_validated: bool = False,
    real_dataset_validated: bool = False,
    billing_credit_verified: bool = False,
    budget_alerts_configured: bool = False,
    microsoft_review_complete: bool = False,
    attestation_path: Path | None = None,
) -> ReadinessDecision:
    reasons: list[str] = []
    run_id: str | None = None
    evidence_mode = "legacy_flags"
    evidence_digest: str | None = None
    try:
        verified = verify_bundle(bundle_dir)
        run_id = str(verified["run_id"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reasons.append(f"evidence bundle verification failed: {exc}")
        return ReadinessDecision(
            READINESS_VERSION, "BLOCK", tuple(reasons), run_id,
            ci_validated, real_dataset_validated, billing_credit_verified,
            budget_alerts_configured, microsoft_review_complete,
            evidence_mode, evidence_digest,
        )

    if attestation_path is not None:
        evidence_mode = "typed_attestations"
        try:
            evidence = load_and_evaluate(attestation_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"attestation evidence failed validation: {exc}")
            return ReadinessDecision(
                READINESS_VERSION, "BLOCK", tuple(reasons), run_id,
                False, False, False, False, False,
                evidence_mode, evidence_digest,
            )
        evidence_digest = evidence.evidence_digest
        ci_validated = evidence.gates["ci_validation"]
        real_dataset_validated = evidence.gates["real_dataset_validation"]
        billing_credit_verified = evidence.gates["billing_credit_linkage"]
        budget_alerts_configured = evidence.gates["budget_alerts"]
        microsoft_review_complete = evidence.gates["microsoft_architecture_review"]
        reasons.extend(evidence.reasons)

    gates = {
        "CI validation is incomplete": ci_validated,
        "exact World Orchids dataset validation is incomplete": real_dataset_validated,
        "nonprofit credit linkage is not verified": billing_credit_verified,
        "subscription budget alerts are not configured": budget_alerts_configured,
        "Microsoft/partner architecture review is incomplete": microsoft_review_complete,
    }
    for message, passed in gates.items():
        if not passed and message not in reasons:
            reasons.append(message)
    decision = "READY_FOR_REVIEW" if not reasons else "HOLD"
    return ReadinessDecision(
        READINESS_VERSION, decision, tuple(reasons), run_id,
        ci_validated, real_dataset_validated, billing_credit_verified,
        budget_alerts_configured, microsoft_review_complete,
        evidence_mode, evidence_digest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate AZURE-001 readiness without granting authority.")
    parser.add_argument("bundle_dir", type=Path)
    for flag in (
        "ci-validated",
        "real-dataset-validated",
        "billing-credit-verified",
        "budget-alerts-configured",
        "microsoft-review-complete",
    ):
        parser.add_argument(f"--{flag}", action="store_true")
    parser.add_argument("--attestations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    decision = evaluate(
        args.bundle_dir,
        ci_validated=args.ci_validated,
        real_dataset_validated=args.real_dataset_validated,
        billing_credit_verified=args.billing_credit_verified,
        budget_alerts_configured=args.budget_alerts_configured,
        microsoft_review_complete=args.microsoft_review_complete,
        attestation_path=args.attestations,
    )
    payload = json.dumps(decision.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if decision.decision == "READY_FOR_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
