#!/usr/bin/env python3
"""Dependency-aware, idempotent reserve-queue refill planner.

This module is deliberately side-effect free. It consumes the canonical
continuous-completion health snapshot plus explicitly authorized engineering
candidates and returns bounded issue proposals. Callers remain responsible for
GitHub mutation and must preserve repository governance.
"""

from __future__ import annotations

from typing import Any

from scripts.oc_health_contract import evaluate

AUTHORIZED_SOURCE_KINDS = {"issue", "template", "objective"}
PROTECTED_BOUNDARIES = {
    "production",
    "scientific",
    "provenance",
    "taxonomy",
    "knowledge_graph",
    "sensitive_locality",
    "security",
    "credential",
    "spending",
    "destructive",
    "governance",
}


def _fingerprints(snapshot: dict[str, Any]) -> set[str]:
    seen = {str(value) for value in snapshot.get("dispatch_fingerprints") or [] if value}
    for issue in snapshot.get("issues") or []:
        value = issue.get("material_fingerprint") or issue.get("fingerprint")
        if value:
            seen.add(str(value))
    return seen


def _semantic_keys(snapshot: dict[str, Any]) -> set[str]:
    seen: set[str] = set()
    for issue in snapshot.get("issues") or []:
        value = issue.get("semantic_key")
        if value:
            seen.add(str(value))
    return seen


def _candidate_reason(candidate: dict[str, Any], completed: set[str], seen_fp: set[str], seen_semantic: set[str]) -> str | None:
    if candidate.get("source_kind") not in AUTHORIZED_SOURCE_KINDS or not candidate.get("source_ref"):
        return "unauthorized_source"

    boundaries = {str(value) for value in candidate.get("protected_boundaries") or []}
    if boundaries & PROTECTED_BOUNDARIES:
        return "protected_boundary"

    fingerprint = candidate.get("material_fingerprint")
    if not fingerprint:
        return "missing_fingerprint"
    if str(fingerprint) in seen_fp:
        return "duplicate_fingerprint"

    semantic_key = candidate.get("semantic_key")
    if semantic_key and str(semantic_key) in seen_semantic:
        return "semantic_duplicate"

    dependencies = {str(value) for value in candidate.get("dependencies") or []}
    if not dependencies.issubset(completed):
        return "dependency_blocked"

    return None


def plan_refill(
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    reserve_depth: int = 2,
    planner_ok: bool = True,
) -> dict[str, Any]:
    """Return a deterministic bounded refill plan without mutating GitHub.

    Candidates must identify an existing authorized issue/template/objective,
    carry a stable material fingerprint, and declare dependencies/protected
    boundaries. The planner never expands authority from candidate content.
    """
    if reserve_depth < 0:
        raise ValueError("reserve_depth must be >= 0")

    health = evaluate(snapshot)
    queued_count = health["counts"]["queued"]
    deficit = max(reserve_depth - queued_count, 0)

    result: dict[str, Any] = {
        "schema": "oc.reserve-refill.v1",
        "reserve_depth": reserve_depth,
        "queued_count": queued_count,
        "deficit": deficit,
        "status": "reserve_satisfied" if deficit == 0 else "refill_needed",
        "proposals": [],
        "rejections": [],
    }

    if not health["healthy"]:
        result["status"] = "queue_empty_planner_failed" if queued_count == 0 else "planner_failed"
        result["rejections"].append({"reason": "health_contract_violation", "violations": health["violations"]})
        return result

    if not planner_ok:
        result["status"] = "queue_empty_planner_failed" if queued_count == 0 else "planner_failed"
        result["rejections"].append({"reason": "planner_unavailable"})
        return result

    if deficit == 0:
        return result

    completed = {str(value) for value in snapshot.get("completed_dependencies") or []}
    seen_fp = _fingerprints(snapshot)
    seen_semantic = _semantic_keys(snapshot)

    ordered = sorted(
        candidates,
        key=lambda item: (
            int(item.get("priority", 999)),
            str(item.get("created_at") or ""),
            str(item.get("source_ref") or ""),
        ),
    )

    for candidate in ordered:
        reason = _candidate_reason(candidate, completed, seen_fp, seen_semantic)
        if reason:
            result["rejections"].append({"source_ref": candidate.get("source_ref"), "reason": reason})
            continue

        fingerprint = str(candidate["material_fingerprint"])
        semantic_key = candidate.get("semantic_key")
        proposal = {
            "source_ref": candidate["source_ref"],
            "source_kind": candidate["source_kind"],
            "title": candidate.get("title"),
            "labels": ["oc-queued"],
            "dependencies": list(candidate.get("dependencies") or []),
            "material_fingerprint": fingerprint,
            "semantic_key": semantic_key,
        }
        result["proposals"].append(proposal)
        seen_fp.add(fingerprint)
        if semantic_key:
            seen_semantic.add(str(semantic_key))
        if len(result["proposals"]) >= deficit:
            break

    if result["proposals"]:
        result["status"] = "refill_planned"
    elif queued_count == 0:
        # An empty queue with only dependency/protected/duplicate candidates is
        # truthful exhaustion, not planner failure and not permission to invent work.
        result["status"] = "queue_empty_healthy"
    else:
        result["status"] = "reserve_below_target_no_eligible_candidates"

    return result
