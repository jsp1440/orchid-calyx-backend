"""Governed, read-only agent context derived from canonical workflow state."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .ranking import FORMULA_VERSION
from .workflow import (
    CONTRACT_VERSION,
    WorkflowState,
    WorkflowType,
    legal_next_states,
)

CONTEXT_VERSION = "governed-agent-context-v1"
MAX_CONTEXT_ITEMS = 16

_SAFE_REFERENCE = re.compile(
    r"^(?:event|artifact|review|issue|commit):[A-Za-z0-9][A-Za-z0-9._:/-]{0,179}$"
)
_FORBIDDEN_KEYS = (
    "api_key",
    "password",
    "secret",
    "token",
    "raw_prompt",
    "prompt_text",
    "latitude",
    "longitude",
    "coordinate",
    "exact_locality",
)
_SECRET_MARKERS = ("sk-", "BEGIN PRIVATE KEY", "Bearer ")

_WORKFLOW_GOALS = {
    WorkflowType.SOURCE_INGESTION: "ingest evidence through governed stages",
    WorkflowType.TAXONOMY_RECONCILIATION: "prepare taxonomy reconciliation for review",
    WorkflowType.SCIENTIFIC_VERIFICATION: "verify evidence without publishing conclusions",
    WorkflowType.CALYX_MISSION: "complete a bounded Calyx mission",
    WorkflowType.BUILD_CI_VALIDATION: "validate a bounded integration candidate",
    WorkflowType.GOVERNED_AGENT_TASK: "prepare a bounded implementation for review",
}

_ACTION_CODES = {
    WorkflowState.BLOCKED: "RECORD_BLOCKER",
    WorkflowState.REVIEW_REQUIRED: "REQUEST_HUMAN_REVIEW",
    WorkflowState.FAILED: "RECORD_FAILURE",
    WorkflowState.COMPLETED: "RECORD_COMPLETION",
    WorkflowState.CANCELLED: "CANCEL",
}

_RECONSTRUCTION_KEYS = frozenset(
    {
        "contract_version",
        "workflow_id",
        "workflow_type",
        "correlation_id",
        "current_state",
        "stages",
        "retry_count",
        "rework_count",
        "evidence_refs",
        "blocker_refs",
        "findings",
        "authoritative_state_mutated",
        "publication_authority",
    }
)
_RANKING_KEYS = frozenset(
    {
        "formula_version",
        "opportunity_id",
        "workflow_id",
        "score",
        "factor_coverage",
        "factors",
        "unavailable_factors",
        "reason_codes",
        "requires_human_approval",
        "advisory_only",
        "dispatch_authority",
        "mutation_authority",
        "publication_authority",
        "spending_authority",
    }
)


class ContextValidationError(ValueError):
    """Raised when source contracts cannot safely produce agent context."""


def _assert_no_sensitive_content(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in _FORBIDDEN_KEYS):
                raise ContextValidationError("source context contains a forbidden field")
            _assert_no_sensitive_content(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            _assert_no_sensitive_content(nested)
    elif isinstance(value, str) and any(marker in value for marker in _SECRET_MARKERS):
        raise ContextValidationError("source context contains secret-like content")


def _bounded_strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_CONTEXT_ITEMS:
        raise ContextValidationError(f"{name} must be a bounded list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _SAFE_REFERENCE.fullmatch(item):
            raise ContextValidationError(f"{name} contains an unsafe reference")
        if item not in result:
            result.append(item)
    return result


def _action_code(current: WorkflowState, target: WorkflowState) -> str:
    if target is WorkflowState.RUNNING:
        return {
            WorkflowState.QUEUED: "START",
            WorkflowState.RUNNING: "CONTINUE",
            WorkflowState.BLOCKED: "RESUME",
            WorkflowState.REVIEW_REQUIRED: "RESUME_AFTER_REVIEW",
            WorkflowState.FAILED: "RETRY",
        }[current]
    return _ACTION_CODES[target]


def _context_status(
    state: WorkflowState,
    *,
    blockers: list[str],
    findings: list[dict[str, Any]],
    ranking_requires_review: bool,
) -> str:
    if state in {WorkflowState.COMPLETED, WorkflowState.CANCELLED}:
        return "BLOCKED" if findings or ranking_requires_review else "TERMINAL"
    if state is WorkflowState.REVIEW_REQUIRED:
        return "AWAITING_REVIEW"
    if blockers or state in {WorkflowState.BLOCKED, WorkflowState.FAILED}:
        return "BLOCKED"
    if ranking_requires_review:
        return "AWAITING_REVIEW"
    return "READY"


def build_governed_agent_context(
    reconstruction: Mapping[str, Any],
    ranking: Mapping[str, Any],
) -> dict[str, Any]:
    """Build context with legal actions only and no execution authority."""

    _assert_no_sensitive_content(reconstruction)
    _assert_no_sensitive_content(ranking)
    if set(reconstruction) != _RECONSTRUCTION_KEYS:
        raise ContextValidationError("unsupported workflow reconstruction shape")
    if set(ranking) != _RANKING_KEYS:
        raise ContextValidationError("unsupported opportunity ranking shape")
    if reconstruction.get("contract_version") != CONTRACT_VERSION:
        raise ContextValidationError("unsupported workflow reconstruction version")
    if ranking.get("formula_version") != FORMULA_VERSION:
        raise ContextValidationError("unsupported opportunity ranking version")
    if reconstruction.get("workflow_id") != ranking.get("workflow_id"):
        raise ContextValidationError("workflow identity mismatch")
    if (
        reconstruction.get("authoritative_state_mutated") is not False
        or reconstruction.get("publication_authority") is not False
        or ranking.get("advisory_only") is not True
        or ranking.get("dispatch_authority") is not False
        or ranking.get("mutation_authority") is not False
        or ranking.get("publication_authority") is not False
        or ranking.get("spending_authority") is not False
    ):
        raise ContextValidationError("source contracts attempt to expand authority")

    try:
        workflow_type = WorkflowType(reconstruction.get("workflow_type"))
        current = WorkflowState(reconstruction.get("current_state"))
    except (TypeError, ValueError) as exc:
        raise ContextValidationError("unsupported workflow type or state") from exc

    workflow_id = reconstruction.get("workflow_id")
    correlation_id = reconstruction.get("correlation_id")
    if not isinstance(workflow_id, str) or not workflow_id or len(workflow_id) > 120:
        raise ContextValidationError("workflow_id is not bounded")
    if (
        not isinstance(correlation_id, str)
        or not _SAFE_REFERENCE.fullmatch(f"event:{correlation_id}")
    ):
        raise ContextValidationError("correlation_id is not a safe event identifier")

    evidence = _bounded_strings(reconstruction.get("evidence_refs"), "evidence_refs")
    blockers = _bounded_strings(reconstruction.get("blocker_refs"), "blocker_refs")
    stages = reconstruction.get("stages")
    findings = reconstruction.get("findings")
    if not isinstance(stages, list) or len(stages) > MAX_CONTEXT_ITEMS:
        raise ContextValidationError("stages must be a bounded list")
    if not isinstance(findings, list) or len(findings) > MAX_CONTEXT_ITEMS:
        raise ContextValidationError("findings must be a bounded list")

    completed_stages: list[str] = []
    for stage in stages[:-1]:
        stage_name = stage.get("stage") if isinstance(stage, Mapping) else None
        resulting_state = (
            stage.get("resulting_state") if isinstance(stage, Mapping) else None
        )
        if (
            isinstance(stage_name, str)
            and resulting_state not in {"blocked", "failed", "cancelled"}
            and stage_name not in completed_stages
        ):
            completed_stages.append(stage_name)

    actions = [
        {
            "action": _action_code(current, target),
            "resulting_state": target.value,
        }
        for target in legal_next_states(current)
    ]

    finding_codes = {
        finding.get("reason_code")
        for finding in findings
        if isinstance(finding, Mapping)
    }
    required_evidence = ["TRANSITION_EVENT"]
    if "MISSING_COMPLETION_EVIDENCE" in finding_codes:
        required_evidence.append("COMPLETION_EVIDENCE")
    if current is WorkflowState.REVIEW_REQUIRED:
        required_evidence.append("HUMAN_REVIEW_DECISION")

    acceptance_criteria = [
        "LEGAL_TRANSITION_RECORDED",
        "REQUIRED_EVIDENCE_ATTACHED",
        "GOVERNANCE_RESTRICTIONS_PRESERVED",
    ]
    if ranking.get("requires_human_approval") is True:
        acceptance_criteria.append("HUMAN_APPROVAL_RECORDED")

    return {
        "contract_version": CONTEXT_VERSION,
        "context_id": f"context:{workflow_id}:{current.value}",
        "workflow_id": workflow_id,
        "correlation_id": correlation_id,
        "goal": _WORKFLOW_GOALS[workflow_type],
        "current_stage": stages[-1].get("stage") if stages else None,
        "current_state": current.value,
        "completed_stages": completed_stages,
        "next_legal_actions": actions,
        "blocker_refs": blockers,
        "evidence_refs": evidence,
        "required_evidence": required_evidence,
        "acceptance_criteria": acceptance_criteria,
        "status": _context_status(
            current,
            blockers=blockers,
            findings=findings,
            ranking_requires_review=ranking.get("requires_human_approval") is True,
        ),
        "risk_cost_constraints": {
            "advisory_score": ranking.get("score"),
            "human_approval_required": ranking.get("requires_human_approval") is True,
            "cost_state": "UNAVAILABLE",
            "spending_limit": None,
        },
        "governance_restrictions": [
            "NO_AUTONOMOUS_DISPATCH",
            "NO_CREDENTIAL_ACCESS",
            "NO_PAID_PROVIDER",
            "NO_PROTECTED_LOCALITY",
            "NO_SCIENTIFIC_OR_TAXONOMY_MUTATION",
            "NO_PUBLICATION",
            "NO_SPENDING",
        ],
        "dispatch_authority": False,
        "credential_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }
