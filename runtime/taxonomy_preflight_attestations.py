"""Validate durable evidence for AZURE-001 external readiness gates.

This module replaces free-form boolean assertions with typed, checksummed
attestations. It does not authorize Azure provisioning, publication, database
mutation, or production migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ATTESTATION_SCHEMA_VERSION = "1.0.0"
GATES = (
    "ci_validation",
    "real_dataset_validation",
    "billing_credit_linkage",
    "budget_alerts",
    "microsoft_architecture_review",
)
REQUIRED_ATTESTATION_FIELDS = {
    "gate", "status", "evidence_id", "issuer", "issued_at",
    "evidence_sha256", "scope",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GateAttestation:
    gate: str
    status: str
    evidence_id: str
    issuer: str
    issued_at: str
    evidence_sha256: str
    scope: str
    expires_at: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class AttestationEvaluation:
    schema_version: str
    valid: bool
    evidence_digest: str
    gates: dict[str, bool]
    reasons: tuple[str, ...]
    attestations: tuple[GateAttestation, ...]
    azure_provisioning_authorized: bool = False
    taxonomy_publication_authorized: bool = False
    database_mutation_authorized: bool = False
    production_migration_authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attestations"] = [asdict(item) for item in self.attestations]
        return payload


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_gate_metadata(item: GateAttestation) -> None:
    if item.metadata is not None and not isinstance(item.metadata, dict):
        raise ValueError(f"metadata must be an object: {item.gate}")
    metadata = item.metadata or {}
    if item.gate == "ci_validation":
        for key in ("repository", "commit_sha", "workflow_run_id"):
            if not str(metadata.get(key, "")).strip():
                raise ValueError(f"ci_validation metadata requires {key}")
        if not GIT_COMMIT_RE.fullmatch(str(metadata["commit_sha"]).casefold()):
            raise ValueError("ci_validation commit_sha must be a 40- or 64-character hex digest")
    elif item.gate == "real_dataset_validation":
        for key in ("source_filename", "source_sha256", "validator_run_id"):
            if not str(metadata.get(key, "")).strip():
                raise ValueError(f"real_dataset_validation metadata requires {key}")
        if not SHA256_RE.fullmatch(str(metadata["source_sha256"]).casefold()):
            raise ValueError("real_dataset_validation source_sha256 is invalid")
    elif item.gate == "billing_credit_linkage":
        for key in ("subscription_id", "billing_profile", "credit_expiration"):
            if not str(metadata.get(key, "")).strip():
                raise ValueError(f"billing_credit_linkage metadata requires {key}")
        _parse_timestamp(str(metadata["credit_expiration"]), "credit_expiration")
    elif item.gate == "budget_alerts":
        thresholds = metadata.get("thresholds_percent")
        if not isinstance(thresholds, list) or not thresholds:
            raise ValueError("budget_alerts metadata requires thresholds_percent")
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= 100 for value in thresholds):
            raise ValueError("budget alert thresholds must be numbers in (0, 100]")
    elif item.gate == "microsoft_architecture_review":
        for key in ("review_reference", "reviewer_organization", "review_outcome"):
            if not str(metadata.get(key, "")).strip():
                raise ValueError(f"microsoft_architecture_review metadata requires {key}")
        if metadata["review_outcome"] not in {"accepted", "accepted_with_actions"}:
            raise ValueError("unsupported architecture review outcome")


def _construct_attestation(raw: dict[str, Any]) -> GateAttestation:
    fields = set(GateAttestation.__dataclass_fields__)
    unknown = sorted(set(raw) - fields)
    if unknown:
        raise ValueError(f"unknown attestation fields: {', '.join(unknown)}")
    missing = sorted(REQUIRED_ATTESTATION_FIELDS - set(raw))
    if missing:
        raise ValueError(f"missing attestation fields: {', '.join(missing)}")
    try:
        return GateAttestation(**raw)
    except TypeError as exc:
        raise ValueError(f"invalid attestation structure: {exc}") from exc


def load_and_evaluate(path: Path, *, now: datetime | None = None) -> AttestationEvaluation:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("attestation register must be a JSON object")
    if set(payload) - {"schema_version", "attestations"}:
        raise ValueError("attestation register contains unknown top-level fields")
    if payload.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        raise ValueError("unsupported attestation schema version")
    raw_items = payload.get("attestations")
    if not isinstance(raw_items, list):
        raise ValueError("attestations must be a list")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seen: set[str] = set()
    reasons: list[str] = []
    parsed_items: list[GateAttestation] = []
    gates = {gate: False for gate in GATES}

    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("each attestation must be a JSON object")
        item = _construct_attestation(raw)
        if item.gate not in GATES:
            raise ValueError(f"unknown readiness gate: {item.gate}")
        if item.gate in seen:
            raise ValueError(f"duplicate readiness gate: {item.gate}")
        seen.add(item.gate)
        if item.status not in {"verified", "rejected", "pending"}:
            raise ValueError(f"invalid attestation status for {item.gate}")
        if not all(isinstance(value, str) for value in (item.evidence_id, item.issuer, item.issued_at, item.evidence_sha256, item.scope)):
            raise ValueError(f"attestation text fields must be strings: {item.gate}")
        if not item.evidence_id.strip() or not item.issuer.strip() or not item.scope.strip():
            raise ValueError(f"attestation identity fields may not be empty: {item.gate}")
        if not SHA256_RE.fullmatch(item.evidence_sha256.casefold()):
            raise ValueError(f"invalid evidence_sha256 for {item.gate}")
        issued = _parse_timestamp(item.issued_at, f"{item.gate}.issued_at")
        if issued > current:
            raise ValueError(f"attestation is future-dated: {item.gate}")
        expired = False
        if item.expires_at:
            expired = _parse_timestamp(item.expires_at, f"{item.gate}.expires_at") <= current
        _validate_gate_metadata(item)
        parsed_items.append(item)
        gates[item.gate] = item.status == "verified" and not expired
        if item.status != "verified":
            reasons.append(f"{item.gate} status is {item.status}")
        elif expired:
            reasons.append(f"{item.gate} attestation is expired")

    for gate in GATES:
        if gate not in seen:
            reasons.append(f"missing attestation: {gate}")

    digest_payload = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "attestations": [asdict(item) for item in sorted(parsed_items, key=lambda value: value.gate)],
    }
    return AttestationEvaluation(
        schema_version=ATTESTATION_SCHEMA_VERSION,
        valid=not reasons,
        evidence_digest=_canonical_digest(digest_payload),
        gates=gates,
        reasons=tuple(reasons),
        attestations=tuple(sorted(parsed_items, key=lambda value: value.gate)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AZURE-001 external gate attestations.")
    parser.add_argument("register", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = load_and_evaluate(args.register)
        payload = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0 if result.valid else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
