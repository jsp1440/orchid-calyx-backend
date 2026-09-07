#!/usr/bin/env python3
"""Build a redacted, read-only operations status payload for Calyx monitors.

The canonical health decision remains in ``oc_health_contract.evaluate``. This
module only projects that result plus explicitly allow-listed operational fields
into a stable public payload; unknown input fields are intentionally discarded.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from scripts.oc_health_contract import evaluate

SCHEMA_VERSION = "oc.operations-status.v1"


def _lease_status(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    leases = list(snapshot.get("leases") or [])
    for issue in snapshot.get("issues") or []:
        inline = issue.get("lease")
        if isinstance(inline, dict):
            item = dict(inline)
            item.setdefault("issue", issue.get("number", issue.get("id")))
            leases.append(item)

    public: list[dict[str, Any]] = []
    for lease in leases:
        if not lease.get("active", True):
            continue
        public.append(
            {
                "issue": lease.get("issue"),
                "lane": lease.get("lane") or lease.get("owner"),
                "age_seconds": lease.get("age_seconds"),
                "stale": bool(lease.get("stale", False)),
            }
        )
    return public


def _autonomous_prs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for pr in snapshot.get("autonomous_prs") or []:
        public.append(
            {
                "number": pr.get("number"),
                "head_sha": pr.get("head_sha"),
                "ci_state": pr.get("ci_state"),
                "mergeable": pr.get("mergeable"),
            }
        )
    return public


def _provider_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    provider = snapshot.get("provider") or {}
    return {
        "status": provider.get("status"),
        "degraded": bool(provider.get("degraded", False)),
        "reason_code": provider.get("reason_code"),
    }


def _integration_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    integration = snapshot.get("integration") or {}
    return {
        "ready": bool(integration.get("ready", False)),
        "target": integration.get("target"),
        "head_sha": integration.get("head_sha"),
        "ahead_by": integration.get("ahead_by"),
    }


def build_operations_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a stable, redacted projection of the canonical health snapshot."""

    report = evaluate(snapshot)
    decision = report["exception_decision"]
    return {
        "schema_version": SCHEMA_VERSION,
        "healthy": report["healthy"],
        "counts": report["counts"],
        "issues": report["issues"],
        "lanes": _lease_status(snapshot),
        "validating_targets": report["validating_targets"],
        "autonomous_prs": _autonomous_prs(snapshot),
        "violations": report["violations"],
        "provider": _provider_status(snapshot),
        "integration": _integration_status(snapshot),
        "exception_class": decision["exception_class"],
        "owner_decision_required": decision["owner_decision_required"],
        "owner_exception_category": decision["owner_exception_category"],
        "autonomous_repair_available": decision["autonomous_repair_available"],
        "independent_authorized_work_available": decision[
            "independent_authorized_work_available"
        ],
        "should_interrupt_owner": decision["should_interrupt_owner"],
    }


def main() -> int:
    try:
        snapshot = json.load(sys.stdin)
    except Exception as exc:
        json.dump(
            {
                "schema_version": SCHEMA_VERSION,
                "healthy": False,
                "error": "invalid_snapshot",
                "detail": type(exc).__name__,
            },
            sys.stdout,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 2

    json.dump(build_operations_status(snapshot), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
