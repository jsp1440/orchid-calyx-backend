#!/usr/bin/env python3
"""Auditable ten-cycle autonomy proof.

Runs ten consecutive provider-free Portfolio Steward cycles through the real
reconcile -> admit -> durable reservoir -> bounded dispatcher -> evidence path.
Each cycle uses a unique issue and carries prior semantic/fingerprint state
forward. It also probes the just-completed task a second time and requires
deduplication to suppress re-admission.

This proves the deterministic autonomous core. It does not claim that an
external scheduler, GitHub credential, Render service, or paid-provider lane
was exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.portfolio_steward_reconciler import reconcile

PROOF_SCHEMA = "oc.autonomy-ten-cycle-proof.v1"
CYCLES = 10


def issue(number: int) -> dict:
    return {
        "number": number,
        "title": f"Autonomy proof cycle {number}",
        "labels": [{"name": "oc-prepared"}, {"name": "oc-p1"}],
        "createdAt": "2026-09-20T00:00:00Z",
    }


def main() -> int:
    snapshot: dict = {"issues": [], "leases": [], "dispatch_fingerprints": []}
    cycles: list[dict] = []
    run_ids: set[str] = set()

    for index in range(1, CYCLES + 1):
        number = 9000 + index
        report = reconcile(
            [issue(number)],
            snapshot,
            run_id=f"autonomy-proof-{index:02d}",
            reserve_depth=1,
            max_tasks=1,
            max_iterations=3,
        )

        assert report.run_id not in run_ids, "duplicate run id"
        run_ids.add(report.run_id)
        assert report.canonical_context_schema == "oc.autonomy-context.v1"
        assert report.canonical_context_version == "1.0.0"
        assert report.source_count == 1
        assert report.admitted_count == 1
        assert report.executed_count == 1
        assert report.blocked_count == 0
        assert report.rejected_count == 0
        assert report.provider_launch_authorized is False
        assert report.no_api_mode is True
        assert len(report.evidence) == 1

        evidence = report.evidence[0]
        assert evidence["issue_number"] == number
        assert evidence["state"] == "completed"
        assert evidence["provider_api_called"] is False
        assert evidence["evidence"] is not None

        proposal = report.bridge_result["proposals"][0]
        snapshot["issues"].append(
            {
                "number": number,
                "labels": ["oc-done"],
                "material_fingerprint": proposal["material_fingerprint"],
                "semantic_key": proposal["semantic_key"],
            }
        )

        # Duplicate-lease/re-admission probe: the exact completed work must not
        # enter the reserve again once its durable identity is in the snapshot.
        duplicate_probe = reconcile(
            [issue(number)],
            snapshot,
            run_id=f"autonomy-proof-{index:02d}-dedup",
            reserve_depth=1,
            max_tasks=1,
            max_iterations=3,
        )
        assert duplicate_probe.admitted_count == 0
        assert duplicate_probe.executed_count == 0
        assert duplicate_probe.blocked_count == 0
        assert duplicate_probe.no_api_mode is True

        cycles.append(
            {
                "cycle": index,
                "run_id": report.run_id,
                "issue_number": number,
                "terminal_state": evidence["state"],
                "admitted_count": report.admitted_count,
                "executed_count": report.executed_count,
                "blocked_count": report.blocked_count,
                "provider_api_called": evidence["provider_api_called"],
                "canonical_context_schema": report.canonical_context_schema,
                "canonical_context_version": report.canonical_context_version,
                "duplicate_probe_admitted_count": duplicate_probe.admitted_count,
                "bridge_status": report.bridge_result.get("status"),
            }
        )

    result = {
        "schema": PROOF_SCHEMA,
        "status": "PASS",
        "consecutive_cycles": len(cycles),
        "target": CYCLES,
        "provider_calls": 0,
        "unhandled_blockages": 0,
        "duplicate_readmissions": 0,
        "missing_completion_evidence": 0,
        "cycles": cycles,
    }

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/autonomy-ten-cycle-proof.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
