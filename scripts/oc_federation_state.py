"""Build and validate the provider-free OC federation work record.

The record is deliberately transport-neutral. A workflow may retain it as an
artifact, comment, or repository file; consumers must validate the exact
implementation, verification, and integration SHAs before using it to unblock
downstream work. This module never calls GitHub, a provider, or a database.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from typing import Any

SCHEMA = "oc.federation-work-record.v1"
HEX40 = re.compile(r"^[a-f0-9]{40}$")
STATES = frozenset({
    "discovered", "admitted", "leased", "executing", "verifying",
    "integrated", "settled", "blocked", "failed",
})
BLOCK_REASONS = frozenset({
    "none", "repository_dependency", "external_provider", "owner_gate",
    "deterministic_failure",
})
LEASE_STATES = frozenset({"none", "reserved", "running", "released", "expired", "blocked"})
SETTLEMENT_STATES = frozenset({"pending", "settled", "not-executed", "failed", "owner-gate"})
REQUIRED = (
    "work_id", "repository", "issue", "pull_request", "capability", "dependencies",
    "dependency_repository", "state", "block_reason", "lease", "attempt",
    "implementation_sha", "verification_sha", "integration_sha", "receipt",
    "provider_requirement", "owner_gate", "settlement", "downstream_dependents",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def _repo(value: Any, field: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[^/]+/[^/]+", value):
        _fail(f"{field}_invalid")


def _optional_sha(value: Any, field: str) -> None:
    if value is not None and (not isinstance(value, str) or not HEX40.fullmatch(value)):
        _fail(f"{field}_invalid")


def _positive_or_none(value: Any, field: str) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        _fail(f"{field}_invalid")


def _references(rows: Any, field: str) -> None:
    if not isinstance(rows, list):
        _fail(f"{field}_invalid")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("work_id"), str) or not row["work_id"]:
            _fail(f"{field}_work_id_invalid")
        _repo(row.get("repository"), f"{field}_repository")


def validate_work_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete record and return it unchanged.

    The cross-field rules are the important part: a consumer must not treat a
    provider, owner, repository, or deterministic failure as a settled success.
    """
    if not isinstance(record, dict):
        _fail("record_invalid")
    missing = [name for name in REQUIRED if name not in record]
    if missing:
        _fail("missing:" + ",".join(missing))
    if record.get("schema") != SCHEMA:
        _fail("schema_invalid")
    if not isinstance(record["work_id"], str) or not record["work_id"]:
        _fail("work_id_invalid")
    _repo(record["repository"], "repository")
    _positive_or_none(record["issue"], "issue")
    _positive_or_none(record["pull_request"], "pull_request")
    capabilities = record["capability"]
    if (not isinstance(capabilities, list) or not capabilities or
            any(not isinstance(name, str) or not name for name in capabilities) or
            len(set(capabilities)) != len(capabilities)):
        _fail("capability_invalid")
    _references(record["dependencies"], "dependencies")
    repositories = record["dependency_repository"]
    if (not isinstance(repositories, list) or len(set(repositories)) != len(repositories)):
        _fail("dependency_repository_invalid")
    for repository in repositories:
        _repo(repository, "dependency_repository")
    state = record["state"]
    if state not in STATES:
        _fail("state_invalid")
    reason = record["block_reason"]
    if reason not in BLOCK_REASONS:
        _fail("block_reason_invalid")
    if reason != "none" and state not in {"blocked", "failed"}:
        _fail("blocked_record_not_blocked")
    if reason == "external_provider" and record["provider_requirement"] is not True:
        _fail("provider_block_without_provider_requirement")
    if record["owner_gate"] is not (reason == "owner_gate"):
        _fail("owner_gate_mismatch")
    lease = record["lease"]
    if not isinstance(lease, dict) or lease.get("state") not in LEASE_STATES:
        _fail("lease_invalid")
    attempt = record["attempt"]
    if (not isinstance(attempt, dict) or not isinstance(attempt.get("run_id"), str) or
            not attempt["run_id"] or not isinstance(attempt.get("run_attempt"), str) or
            not attempt["run_attempt"]):
        _fail("attempt_invalid")
    _optional_sha(record["implementation_sha"], "implementation_sha")
    _optional_sha(record["verification_sha"], "verification_sha")
    _optional_sha(record["integration_sha"], "integration_sha")
    receipt = record["receipt"]
    if (not isinstance(receipt, dict) or not all(isinstance(receipt.get(key), str) and receipt[key]
                                                   for key in ("schema", "kind", "id"))):
        _fail("receipt_invalid")
    settlement = record["settlement"]
    if not isinstance(settlement, dict) or settlement.get("state") not in SETTLEMENT_STATES:
        _fail("settlement_invalid")
    if state == "settled" and settlement["state"] != "settled":
        _fail("settled_record_without_settlement")
    _references(record["downstream_dependents"], "downstream_dependents")
    if record["provider_requirement"] is not False and state == "settled":
        _fail("provider_settled_without_provider_evidence")
    return record


def build_backend_completion(
    *,
    repository: str,
    work_id: str,
    integration_sha: str,
    verification_sha: str,
    run_id: str,
    run_attempt: str,
    capabilities: Iterable[str],
    downstream_dependents: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Create the exact-head, settled backend integration handoff."""
    record = {
        "schema": SCHEMA,
        "work_id": work_id,
        "repository": repository,
        "issue": None,
        "pull_request": None,
        "capability": sorted(set(capabilities)),
        "dependencies": [],
        "dependency_repository": [],
        "state": "settled",
        "block_reason": "none",
        "lease": {"state": "released", "lease_id": None},
        "attempt": {"run_id": str(run_id), "run_attempt": str(run_attempt)},
        "implementation_sha": integration_sha,
        "verification_sha": verification_sha,
        "integration_sha": integration_sha,
        "receipt": {
            "schema": "oc.federation-receipt.v1",
            "kind": "github-actions-run",
            "id": str(run_id),
        },
        "provider_requirement": False,
        "owner_gate": False,
        "settlement": {"state": "settled", "provider_calls": 0, "provider_cost_usd": 0},
        "downstream_dependents": list(downstream_dependents),
    }
    return validate_work_record(record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--integration-sha", required=True)
    parser.add_argument("--verification-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--capability", action="append", required=True)
    parser.add_argument("--downstream-json", default="[]")
    args = parser.parse_args()
    downstream = json.loads(args.downstream_json)
    if not isinstance(downstream, list):
        raise TypeError("downstream_json_invalid")
    print(json.dumps(build_backend_completion(
        repository=args.repository,
        work_id=args.work_id,
        integration_sha=args.integration_sha,
        verification_sha=args.verification_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        capabilities=args.capability,
        downstream_dependents=downstream,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
