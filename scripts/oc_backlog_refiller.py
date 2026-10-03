"""Dependency-aware, idempotent reserve-queue refill planner.

This module is deliberately side-effect free. It consumes the canonical
continuous-completion health snapshot plus explicitly authorized engineering
candidates and returns bounded issue proposals. Callers remain responsible for
GitHub mutation and must preserve repository governance.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from scripts.oc_health_contract import evaluate

AUTHORIZED_SOURCE_KINDS = {"issue", "template", "objective"}
AUTHORIZED_QUEUE_SOURCE_KINDS = {
    "autonomous-orchestrator",
    "brain-knowledge-gap",
    "self-audit",
    "connector-queue",
    "bounded-engineering-executor",
}
MAX_SOURCE_PAYLOAD_BYTES = 4096
KNOWLEDGE_GAP_PAYLOAD_SCHEMA = "oc.knowledge-gap-reserve-source.v1"
KNOWLEDGE_GAP_STRING_FIELDS = {
    "schema",
    "taxon_id",
    "taxon_name",
    "domain",
    "research_question",
    "execution_mode",
}
KNOWLEDGE_GAP_FALSE_AUTHORITY_FIELDS = {
    "automatic_publication",
    "knowledge_graph_mutation",
    "taxonomy_mutation",
    "sensitive_locality_disclosure",
}
# Health violations that describe one contradictory issue rather than the
# control plane as a whole. Such an issue is skipped and reported as a
# structured conflict finding; it does not fail the whole planner. Every other
# violation still fails the planner closed.
ISSUE_SCOPED_CONFLICT_VIOLATIONS = frozenset({"executable_parked_conflict"})
CONFLICT_FOLLOW_UP_SCHEMA = "oc.queue-conflict-follow-up.v1"
# A reserve whose only queued issues are contradictory is not healthy: nothing
# in it can run. Callers must treat this status as a failure.
QUEUE_BLOCKED_BY_CONFLICTS = "queue_blocked_by_conflicts"

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
    seen = {
        str(value)
        for value in snapshot.get("dispatch_fingerprints") or []
        if value
    }
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


def _source_payload_reason(candidate: dict[str, Any]) -> str | None:
    payload = candidate.get("source_payload")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return "invalid_source_payload"

    allowed = (
        KNOWLEDGE_GAP_STRING_FIELDS
        | KNOWLEDGE_GAP_FALSE_AUTHORITY_FIELDS
        | {"review_required"}
    )
    if set(payload) != allowed:
        return "invalid_source_payload"
    if payload.get("schema") != KNOWLEDGE_GAP_PAYLOAD_SCHEMA:
        return "invalid_source_payload"
    if any(
        not isinstance(payload.get(field), str) or not payload[field].strip()
        for field in KNOWLEDGE_GAP_STRING_FIELDS
    ):
        return "invalid_source_payload"
    if payload.get("execution_mode") != "bounded_research_mission":
        return "authority_escalation"
    if payload.get("review_required") is not True:
        return "authority_escalation"
    if any(payload.get(field) is not False for field in KNOWLEDGE_GAP_FALSE_AUTHORITY_FIELDS):
        return "authority_escalation"

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_SOURCE_PAYLOAD_BYTES:
        return "source_payload_too_large"
    return None


def _candidate_reason(
    candidate: dict[str, Any],
    completed: set[str],
    seen_fp: set[str],
    seen_semantic: set[str],
) -> str | None:
    if (
        candidate.get("source_kind") not in AUTHORIZED_SOURCE_KINDS
        or not candidate.get("source_ref")
    ):
        return "unauthorized_source"

    queue_source_kind = candidate.get("queue_source_kind")
    if (
        queue_source_kind is not None
        and queue_source_kind not in AUTHORIZED_QUEUE_SOURCE_KINDS
    ):
        return "unauthorized_queue_source"

    boundaries = {
        str(value) for value in candidate.get("protected_boundaries") or []
    }
    if boundaries & PROTECTED_BOUNDARIES:
        return "protected_boundary"

    payload_reason = _source_payload_reason(candidate)
    if payload_reason:
        return payload_reason

    fingerprint = candidate.get("material_fingerprint")
    if not fingerprint:
        return "missing_fingerprint"
    if str(fingerprint) in seen_fp:
        return "duplicate_fingerprint"

    semantic_key = candidate.get("semantic_key")
    if semantic_key and str(semantic_key) in seen_semantic:
        return "semantic_duplicate"

    dependencies = {
        str(value) for value in candidate.get("dependencies") or []
    }
    if not dependencies.issubset(completed):
        return "dependency_blocked"

    return None


def _split_issue_conflicts(
    violations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate isolatable per-issue conflicts from planner-blocking violations."""
    conflicts: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    for violation in violations:
        if (
            violation.get("type") in ISSUE_SCOPED_CONFLICT_VIOLATIONS
            and violation.get("issue") is not None
        ):
            conflicts.append(violation)
        else:
            blocking.append(violation)
    return conflicts, blocking


def _conflict_finding(violation: dict[str, Any]) -> dict[str, Any]:
    """A contradictory issue, with the exact relabel that resolves it.

    Resolution is fail-closed: the parked label (backoff or blocked) was set by
    a failure path and wins, so the executable labels are removed. Re-queueing
    is left to that label's own governed exit path; removing the parked label
    instead would re-admit failed work without its retry or review.
    """
    issue = violation["issue"]
    executable = sorted(str(label) for label in violation.get("executable") or [])
    parked = sorted(str(label) for label in violation.get("parked") or [])
    command = ["gh", "issue", "edit", str(issue)]
    for label in executable:
        command += ["--remove-label", label]
    return {
        "type": violation["type"],
        "issue": issue,
        "executable": executable,
        "parked": parked,
        "anomaly": "queue_backoff_contradiction",
        "action": "issue_skipped",
        "counted_as_reserve": False,
        "relabel": {"remove": executable, "add": []},
        "relabel_command": command,
        "resolution": (
            f"Remove {', '.join(executable)} from #{issue}; keep {', '.join(parked)}. "
            "The parked state was set by a failure path and must exit through it."
        ),
    }


def _conflict_follow_up(finding: dict[str, Any]) -> dict[str, Any]:
    """One idempotent issue-comment payload for one conflict.

    The key is derived only from the issue and its conflicting labels, so the
    same unresolved conflict always yields the same key and a poster can skip
    an issue that already carries the marker comment.
    """
    material = json.dumps(
        [finding["issue"], finding["executable"], finding["parked"]],
        separators=(",", ":"),
    )
    key = hashlib.sha256(f"{CONFLICT_FOLLOW_UP_SCHEMA}|{material}".encode()).hexdigest()
    marker = f"<!-- oc-queue-conflict:{key} -->"
    labels = ", ".join(f"`{label}`" for label in finding["executable"] + finding["parked"])
    body = (
        f"{marker}\n"
        f"[OC-QUEUE-CONFLICT] #{finding['issue']} carries both executable and parked "
        f"labels ({labels}). The refill planner skipped it and did not count it as "
        "reserve.\n\n"
        f"Fix: `{' '.join(finding['relabel_command'])}`\n\n"
        f"{finding['resolution']}"
    )
    return {
        "schema": CONFLICT_FOLLOW_UP_SCHEMA,
        "kind": "issue_comment",
        "issue": finding["issue"],
        "idempotency_key": key,
        "marker": marker,
        "relabel": finding["relabel"],
        "relabel_command": finding["relabel_command"],
        "body": body,
    }


def _source_issue_number(candidate: dict[str, Any]) -> Any:
    ref = str(candidate.get("source_ref") or "")
    if ref.startswith("#") and ref[1:].isdigit():
        return int(ref[1:])
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
    conflicts, blocking = _split_issue_conflicts(health["violations"])
    conflict_issues = {violation["issue"] for violation in conflicts}
    # A contradictory issue is not executable reserve: the scheduler parks it.
    queued_count = len(
        [
            ident
            for ident in health["issues"]["queued"]
            if ident not in conflict_issues
        ]
    )
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
    if conflicts:
        # Present only when there is something to report, so a healthy plan
        # keeps the exact wire shape consumers (and the frontend fixture) pin.
        findings: dict[Any, dict[str, Any]] = {}
        for violation in conflicts:
            findings.setdefault(violation["issue"], _conflict_finding(violation))
        result["conflicts"] = list(findings.values())
        # Exactly one follow-up per conflicting issue.
        result["conflict_follow_ups"] = [
            _conflict_follow_up(finding) for finding in findings.values()
        ]

    if blocking:
        result["status"] = (
            "queue_empty_planner_failed" if queued_count == 0 else "planner_failed"
        )
        result["rejections"].append(
            {
                "reason": "health_contract_violation",
                "violations": health["violations"],
            }
        )
        return result

    if not planner_ok:
        result["status"] = (
            "queue_empty_planner_failed" if queued_count == 0 else "planner_failed"
        )
        result["rejections"].append({"reason": "planner_unavailable"})
        return result

    if deficit == 0:
        return result

    completed = {
        str(value) for value in snapshot.get("completed_dependencies") or []
    }
    seen_fp = _fingerprints(snapshot)
    seen_semantic = _semantic_keys(snapshot)

    ordered = sorted(
        candidates,
        key=lambda item: (
            int(item.get("priority", 999)),
            str(item.get("created_at") or ""),
            # Optional source-supplied rank; absent (0) keeps the prior ordering.
            int(item.get("queue_rank") or 0),
            str(item.get("source_ref") or ""),
        ),
    )

    for candidate in ordered:
        if _source_issue_number(candidate) in conflict_issues:
            result["rejections"].append(
                {
                    "source_ref": candidate.get("source_ref"),
                    "reason": "executable_parked_conflict",
                }
            )
            continue
        reason = _candidate_reason(
            candidate,
            completed,
            seen_fp,
            seen_semantic,
        )
        if reason:
            result["rejections"].append(
                {"source_ref": candidate.get("source_ref"), "reason": reason}
            )
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
        # Carried so a consumer does not flatten every source to one priority.
        if isinstance(candidate.get("priority"), int) and not isinstance(
            candidate.get("priority"), bool
        ):
            proposal["priority"] = candidate["priority"]
        if candidate.get("queue_source_kind") is not None:
            proposal["queue_source_kind"] = candidate["queue_source_kind"]
        if candidate.get("required_capabilities") is not None:
            proposal["required_capabilities"] = sorted(
                {
                    str(capability_id)
                    for capability_id in candidate["required_capabilities"]
                }
            )
        if candidate.get("source_payload") is not None:
            proposal["source_payload"] = candidate["source_payload"]
        result["proposals"].append(proposal)
        seen_fp.add(fingerprint)
        if semantic_key:
            seen_semantic.add(str(semantic_key))
        if len(result["proposals"]) >= deficit:
            break

    if result["proposals"]:
        result["status"] = "refill_planned"
    elif queued_count == 0 and conflicts:
        result["status"] = QUEUE_BLOCKED_BY_CONFLICTS
    elif queued_count == 0:
        result["status"] = "queue_empty_healthy"
    else:
        result["status"] = "reserve_below_target_no_eligible_candidates"

    return result
