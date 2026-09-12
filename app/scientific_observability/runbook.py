"""Deterministic, review-required runbooks from canonical workflow evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .agent_context import CONTEXT_VERSION
from .workflow import CONTRACT_VERSION, WorkflowStage, WorkflowState, WorkflowType

RUNBOOK_VERSION = "reviewable-runbook-v1"
MAX_RUNBOOK_ITEMS = 16

_SAFE_REFERENCE = re.compile(
    r"^(?:event|artifact|review|issue|commit):[A-Za-z0-9][A-Za-z0-9._:/-]{0,179}$"
)
_EVENT_ID = re.compile(r"^OC:EVENT:[A-Za-z0-9-]{16,80}$")
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

_PURPOSES = {
    WorkflowType.SOURCE_INGESTION: "ingest evidence through governed stages",
    WorkflowType.TAXONOMY_RECONCILIATION: "prepare taxonomy reconciliation for review",
    WorkflowType.SCIENTIFIC_VERIFICATION: "verify evidence without publishing conclusions",
    WorkflowType.CALYX_MISSION: "complete a bounded Calyx mission",
    WorkflowType.BUILD_CI_VALIDATION: "validate a bounded integration candidate",
    WorkflowType.GOVERNED_AGENT_TASK: "prepare a bounded implementation for review",
}

_STAGE_INSTRUCTIONS = {
    WorkflowStage.QUEUE: "record the authorized workflow in the governed queue",
    WorkflowStage.ACQUIRE: "acquire the declared source through its governed boundary",
    WorkflowStage.NORMALIZE: "normalize the acquired record while preserving provenance",
    WorkflowStage.RECONCILE: "reconcile the candidate without authoritative mutation",
    WorkflowStage.VERIFY: "verify required evidence at the human-review boundary",
    WorkflowStage.EXECUTE: "execute only the bounded authorized operation",
    WorkflowStage.VALIDATE: "validate the exact bounded result",
    WorkflowStage.REVIEW: "obtain and record the required human review",
    WorkflowStage.COMPLETE: "record completion with stable evidence references",
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
_CONTEXT_KEYS = frozenset(
    {
        "contract_version",
        "context_id",
        "workflow_id",
        "correlation_id",
        "goal",
        "current_stage",
        "current_state",
        "completed_stages",
        "next_legal_actions",
        "blocker_refs",
        "evidence_refs",
        "required_evidence",
        "acceptance_criteria",
        "status",
        "risk_cost_constraints",
        "governance_restrictions",
        "dispatch_authority",
        "credential_authority",
        "mutation_authority",
        "publication_authority",
        "spending_authority",
    }
)


class RunbookValidationError(ValueError):
    """Raised when canonical evidence cannot safely produce a runbook."""


def _assert_no_sensitive_content(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in _FORBIDDEN_KEYS):
                raise RunbookValidationError("source contains a forbidden field")
            _assert_no_sensitive_content(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            _assert_no_sensitive_content(nested)
    elif isinstance(value, str) and any(marker in value for marker in _SECRET_MARKERS):
        raise RunbookValidationError("source contains secret-like content")


def _references(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > MAX_RUNBOOK_ITEMS:
        raise RunbookValidationError(f"{name} must be a non-empty bounded list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _SAFE_REFERENCE.fullmatch(item):
            raise RunbookValidationError(f"{name} contains an unsafe reference")
        if item not in result:
            result.append(item)
    return result


def _verified_timestamp(stages: list[Any]) -> str:
    last = stages[-1]
    if not isinstance(last, Mapping):
        raise RunbookValidationError("final stage is malformed")
    value = last.get("recorded_at")
    if not isinstance(value, str):
        raise RunbookValidationError("final stage lacks a recorded timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RunbookValidationError("final stage timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RunbookValidationError("final stage timestamp must be timezone-aware")
    return parsed.isoformat()


def generate_reviewable_runbook(
    reconstruction: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate a deterministic draft runbook, never an approved authority."""

    _assert_no_sensitive_content(reconstruction)
    _assert_no_sensitive_content(context)
    if set(reconstruction) != _RECONSTRUCTION_KEYS:
        raise RunbookValidationError("unsupported workflow reconstruction shape")
    if set(context) != _CONTEXT_KEYS:
        raise RunbookValidationError("unsupported governed context shape")
    if reconstruction.get("contract_version") != CONTRACT_VERSION:
        raise RunbookValidationError("unsupported workflow reconstruction version")
    if context.get("contract_version") != CONTEXT_VERSION:
        raise RunbookValidationError("unsupported governed context version")
    if (
        reconstruction.get("workflow_id") != context.get("workflow_id")
        or reconstruction.get("correlation_id") != context.get("correlation_id")
    ):
        raise RunbookValidationError("workflow context identity mismatch")

    if reconstruction.get("current_state") != WorkflowState.COMPLETED.value:
        raise RunbookValidationError("only completed workflows are eligible")
    if context.get("status") != "TERMINAL" or context.get("current_state") != "completed":
        raise RunbookValidationError("workflow is not cleanly terminal")
    if reconstruction.get("blocker_refs") or context.get("blocker_refs"):
        raise RunbookValidationError("blocked workflows are not eligible")
    if reconstruction.get("findings"):
        raise RunbookValidationError("unresolved workflow findings require review")
    if context.get("next_legal_actions"):
        raise RunbookValidationError("terminal workflow exposes unexpected actions")
    if (
        reconstruction.get("authoritative_state_mutated") is not False
        or reconstruction.get("publication_authority") is not False
        or context.get("dispatch_authority") is not False
        or context.get("credential_authority") is not False
        or context.get("mutation_authority") is not False
        or context.get("publication_authority") is not False
        or context.get("spending_authority") is not False
    ):
        raise RunbookValidationError("source attempts to expand authority")

    evidence_refs = _references(
        reconstruction.get("evidence_refs"),
        "evidence_refs",
    )
    stages = reconstruction.get("stages")
    if not isinstance(stages, list) or not stages or len(stages) > MAX_RUNBOOK_ITEMS:
        raise RunbookValidationError("stages must be a non-empty bounded list")
    try:
        workflow_type = WorkflowType(reconstruction.get("workflow_type"))
    except (TypeError, ValueError) as exc:
        raise RunbookValidationError("unsupported workflow type") from exc
    purpose = _PURPOSES[workflow_type]
    if context.get("goal") != purpose:
        raise RunbookValidationError("governed workflow purpose was altered")

    steps: list[dict[str, Any]] = []
    recovery: list[dict[str, str]] = []
    for number, stage_payload in enumerate(stages, start=1):
        if not isinstance(stage_payload, Mapping):
            raise RunbookValidationError("stage payload is malformed")
        try:
            stage = WorkflowStage(stage_payload.get("stage"))
            state = WorkflowState(stage_payload.get("resulting_state"))
        except (TypeError, ValueError) as exc:
            raise RunbookValidationError("stage uses an unsupported vocabulary") from exc
        event_id = stage_payload.get("event_id")
        if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
            raise RunbookValidationError("stage event_id is invalid")
        stage_evidence = stage_payload.get("evidence_refs")
        if not isinstance(stage_evidence, list) or len(stage_evidence) > MAX_RUNBOOK_ITEMS:
            raise RunbookValidationError("stage evidence is not bounded")
        for reference in stage_evidence:
            if not isinstance(reference, str) or not _SAFE_REFERENCE.fullmatch(reference):
                raise RunbookValidationError("stage evidence contains an unsafe reference")
        steps.append(
            {
                "number": number,
                "stage": stage.value,
                "instruction": _STAGE_INSTRUCTIONS[stage],
                "observed_result": state.value,
                "source_event_id": event_id,
                "expected_evidence_refs": list(stage_evidence),
            }
        )
        if state is WorkflowState.FAILED:
            recovery.append(
                {
                    "after_stage": stage.value,
                    "action": "RETRY_ONLY_THROUGH_LEGAL_TRANSITION",
                }
            )

    final_event_id = steps[-1]["source_event_id"]
    return {
        "contract_version": RUNBOOK_VERSION,
        "runbook_id": f"runbook:{reconstruction['workflow_id']}:{final_event_id}",
        "source_workflow_version": CONTRACT_VERSION,
        "source_context_version": CONTEXT_VERSION,
        "workflow_id": reconstruction["workflow_id"],
        "workflow_type": workflow_type.value,
        "purpose": purpose,
        "prerequisites": [
            "AUTHORIZED_PROJECT_CONTEXT",
            "CANONICAL_OBSERVATION_LEDGER",
            "EVIDENCE_REFERENCES_AVAILABLE",
        ],
        "steps": steps,
        "expected_evidence_refs": evidence_refs,
        "recovery_guidance": recovery or [{"action": "NO_RECORDED_RECOVERY_STEP"}],
        "governance_warnings": list(context.get("governance_restrictions") or []),
        "reviewer_role": "HUMAN_WORKFLOW_OWNER",
        "last_verified_at": _verified_timestamp(stages),
        "generated": True,
        "review_required": True,
        "authoritative": False,
        "approved": False,
        "dispatch_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }
