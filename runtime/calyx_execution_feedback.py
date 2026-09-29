"""Provider-free execution-evidence return contract for the Calyx director.

This module closes the observation side of the governed development loop. It
classifies durable execution evidence into a bounded disposition for Calyx to
reason over; it never performs the resulting action. Queue Bridge remains the
authority for admission, persistence, leases, retries, merges, and owner gates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

_SCHEMA = "oc.calyx-execution-feedback.v1"
_DISPOSITIONS = frozenset({"COMPLETE", "REVISE", "BLOCKED", "OWNER_GATED"})


@dataclass(frozen=True, slots=True)
class ExecutionEvidencePacket:
    task_key: str
    source_key: str
    repo: str
    issue_number: int
    state: str
    exact_head_sha: str | None = None
    pr_number: int | None = None
    tests_passed: bool | None = None
    ci_conclusion: str | None = None
    evidence: dict[str, Any] | None = None
    blocked_reason: str | None = None
    owner_gate_reason: str | None = None
    provider_api_called: bool = False


def _fingerprint(packet: ExecutionEvidencePacket) -> str:
    material = {
        "schema": _SCHEMA,
        "task_key": packet.task_key,
        "source_key": packet.source_key,
        "repo": packet.repo,
        "issue_number": packet.issue_number,
        "state": packet.state,
        "exact_head_sha": packet.exact_head_sha,
        "pr_number": packet.pr_number,
        "tests_passed": packet.tests_passed,
        "ci_conclusion": packet.ci_conclusion,
        "evidence": packet.evidence or {},
        "blocked_reason": packet.blocked_reason,
        "owner_gate_reason": packet.owner_gate_reason,
        "provider_api_called": packet.provider_api_called,
    }
    encoded = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classify_execution_evidence(packet: ExecutionEvidencePacket) -> dict[str, Any]:
    """Return a bounded Calyx disposition without granting action authority."""
    if packet.provider_api_called:
        disposition = "BLOCKED"
        reason = "paid_provider_call_detected"
    elif packet.owner_gate_reason or packet.state == "owner_gated":
        disposition = "OWNER_GATED"
        reason = packet.owner_gate_reason or "owner_gate_required"
    elif packet.state in {"blocked", "repair_backoff"}:
        disposition = "BLOCKED"
        reason = packet.blocked_reason or packet.state
    elif packet.state != "completed":
        disposition = "REVISE"
        reason = "execution_not_terminal_complete"
    elif packet.tests_passed is False or (
        packet.ci_conclusion not in {None, "success"}
    ):
        disposition = "REVISE"
        reason = "verification_failed"
    elif not packet.exact_head_sha or not packet.evidence:
        disposition = "REVISE"
        reason = "completion_evidence_incomplete"
    else:
        disposition = "COMPLETE"
        reason = "verified_execution_complete"

    assert disposition in _DISPOSITIONS
    return {
        "schema": _SCHEMA,
        "fingerprint": _fingerprint(packet),
        "task_key": packet.task_key,
        "source_key": packet.source_key,
        "repo": packet.repo,
        "issue_number": packet.issue_number,
        "disposition": disposition,
        "reason": reason,
        "exact_head_sha": packet.exact_head_sha,
        "pr_number": packet.pr_number,
        "provider_launch_authorized": False,
        "no_api_mode": True,
        "authority": "queue-bridge",
        "action_authorized": False,
    }
