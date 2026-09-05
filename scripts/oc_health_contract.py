#!/usr/bin/env python3
"""Machine-checkable continuous-completion health contract.

Consumes a JSON snapshot on stdin and emits a normalized health report on stdout.
Exit code 0 means the control plane is internally consistent. Exit code 2 means
one or more contract invariants are violated. This checker is deliberately
provider-independent and side-effect free so workflows, observers, and phone
monitoring can share one definition of health.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any

EXECUTABLE = {"oc-queued", "oc-running", "oc-validating"}
NON_EXECUTABLE = {"oc-runtime-backoff", "oc-repair-backoff", "oc-blocked"}


def _labels(issue: dict[str, Any]) -> set[str]:
    raw = issue.get("labels") or []
    result: set[str] = set()
    for label in raw:
        if isinstance(label, str):
            result.add(label)
        elif isinstance(label, dict) and label.get("name"):
            result.add(str(label["name"]))
    return result


def _issue_id(issue: dict[str, Any]) -> Any:
    return issue.get("number", issue.get("id"))


def evaluate(snapshot: dict[str, Any]) -> dict[str, Any]:
    issues = list(snapshot.get("issues") or [])
    leases = list(snapshot.get("leases") or [])
    fingerprints = list(snapshot.get("dispatch_fingerprints") or [])

    # Accept both supported snapshot shapes: a canonical top-level `leases`
    # collection and a lease embedded on the running issue. Normalize the latter
    # into the same invariant checks without weakening lease cardinality.
    for issue in issues:
        inline_lease = issue.get("lease")
        if isinstance(inline_lease, dict):
            normalized = dict(inline_lease)
            normalized.setdefault("issue", _issue_id(issue))
            leases.append(normalized)

    buckets = {
        "queued": [],
        "running": [],
        "validating": [],
        "runtime_backoff": [],
        "repair_backoff": [],
        "blocked": [],
    }
    violations: list[dict[str, Any]] = []

    for issue in issues:
        labels = _labels(issue)
        ident = _issue_id(issue)
        mapping = {
            "oc-queued": "queued",
            "oc-running": "running",
            "oc-validating": "validating",
            "oc-runtime-backoff": "runtime_backoff",
            "oc-repair-backoff": "repair_backoff",
            "oc-blocked": "blocked",
        }
        for label, bucket in mapping.items():
            if label in labels:
                buckets[bucket].append(ident)

        executable = labels & EXECUTABLE
        parked = labels & NON_EXECUTABLE
        if len(executable) > 1:
            violations.append({"type": "multiple_executable_states", "issue": ident, "labels": sorted(executable)})
        if executable and parked:
            violations.append({"type": "executable_parked_conflict", "issue": ident, "executable": sorted(executable), "parked": sorted(parked)})

    lease_issue_counts = Counter(l.get("issue") for l in leases if l.get("active", True))
    running_ids = {i for i in buckets["running"] if i is not None}
    for issue_id in running_ids:
        count = lease_issue_counts.get(issue_id, 0)
        if count != 1:
            violations.append({"type": "running_lease_cardinality", "issue": issue_id, "active_leases": count})

    for lease in leases:
        if not lease.get("active", True):
            continue
        issue_id = lease.get("issue")
        if issue_id not in running_ids:
            violations.append({"type": "orphan_active_lease", "issue": issue_id, "lease": lease.get("id") or lease.get("owner")})
        if lease.get("stale") is True:
            violations.append({"type": "stale_lease", "issue": issue_id, "lease": lease.get("id") or lease.get("owner")})

    for fp, count in Counter(fingerprints).items():
        if fp and count > 1:
            violations.append({"type": "duplicate_dispatch_fingerprint", "fingerprint": fp})

    validating_targets = []
    for issue in issues:
        if "oc-validating" not in _labels(issue):
            continue
        target = issue.get("validation_target") or {}
        head = target.get("head_sha") or issue.get("head_sha")
        pr = target.get("pr") or issue.get("pr")
        validating_targets.append({"issue": _issue_id(issue), "pr": pr, "head_sha": head})
        if not head:
            violations.append({"type": "validating_without_exact_head", "issue": _issue_id(issue), "pr": pr})

    return {
        "healthy": not violations,
        "counts": {name: len(ids) for name, ids in buckets.items()},
        "issues": buckets,
        "validating_targets": validating_targets,
        "provider": snapshot.get("provider") or {},
        "integration": snapshot.get("integration") or {},
        "exceptions": snapshot.get("exceptions") or [],
        "violations": violations,
    }


def main() -> int:
    try:
        snapshot = json.load(sys.stdin)
    except Exception as exc:
        json.dump({"healthy": False, "violations": [{"type": "invalid_snapshot", "error": str(exc)}]}, sys.stdout)
        sys.stdout.write("\n")
        return 2
    report = evaluate(snapshot)
    json.dump(report, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
