"""Read-only reserve plan of KG evidence-gap research missions for the frontend.

Serves ``plan_evidence_gap_refill`` output in the ``BackendReservePlan`` shape
that the frontend's ``backendReserveQueueBridge`` parses. Nothing here leases,
creates issues, writes the KG, or publishes.

Snapshot basis: the backend holds no server-side queue snapshot without a
GitHub token, and fetching one would widen this read-only route's authority.
The plan is therefore computed against an empty queue snapshot, excluding any
material fingerprints the caller already holds; the frontend admission bridge
reconciles against its own existing work (open lineage, titles, depth). The
response states this in ``snapshot_basis``.

Fail-closed: when the KG gap source is unavailable, or the engine fell back to
its stored (keyword-era) record, there are zero proposals and ``status`` is
``evidence_gaps_unavailable`` with ``status_reason``; the frontend bridge
treats any status outside its safe set as a blocked upstream.
"""

from __future__ import annotations

import re
from typing import Any

from runtime.evidence_coverage_gaps import EvidenceCoverageGapSource
from runtime.evidence_gap_reserve_adapter import plan_evidence_gap_refill

UNAVAILABLE_STATUS = "evidence_gaps_unavailable"
SNAPSHOT_BASIS = (
    "empty_queue_snapshot_with_caller_fingerprints: the backend holds no queue "
    "snapshot; the frontend admission bridge reconciles against existing work"
)
MAX_RESERVE_DEPTH = 3
MAX_CALLER_FINGERPRINTS = 100
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def valid_fingerprints(values: list[str]) -> list[str] | None:
    """Caller fingerprints, or ``None`` when any is malformed or there are too many."""
    if len(values) > MAX_CALLER_FINGERPRINTS:
        return None
    cleaned = [value.strip() for value in values]
    if any(not _FINGERPRINT.match(value) for value in cleaned):
        return None
    return sorted(set(cleaned))


def evidence_gap_reserve_plan(
    source: EvidenceCoverageGapSource,
    *,
    reserve_depth: int = MAX_RESERVE_DEPTH,
    fingerprints: list[str] | None = None,
) -> dict[str, Any]:
    depth = max(0, min(MAX_RESERVE_DEPTH, int(reserve_depth)))
    snapshot = {
        "issues": [],
        "leases": [],
        "dispatch_fingerprints": list(fingerprints or []),
    }
    try:
        result = plan_evidence_gap_refill(snapshot, source, reserve_depth=depth)
    except Exception as exc:  # noqa: BLE001 - any failure is a blocked upstream, never a 500
        return {
            "schema": "oc.reserve-refill.v1",
            "reserve_depth": depth,
            "queued_count": 0,
            "deficit": depth,
            "status": UNAVAILABLE_STATUS,
            "status_reason": f"reserve planning failed: {type(exc).__name__}",
            "proposals": [],
            "rejections": [],
            "snapshot_basis": SNAPSHOT_BASIS,
        }
    reason = result.get("source_unavailable_reason")
    if reason or result.get("source_gap_source") != "evidence_coverage_kg":
        result["status"] = UNAVAILABLE_STATUS
        result["status_reason"] = (
            reason or "gap queue did not come from the live knowledge graph"
        )
        result["proposals"] = []
    else:
        result["status_reason"] = None
    result["snapshot_basis"] = SNAPSHOT_BASIS
    return result
