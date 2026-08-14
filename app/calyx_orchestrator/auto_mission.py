from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .executor import ExecutionReceipt, ExecutionState
from .program_models import CalyxProgramJob

OWNER_ONLY_ACTIONS = frozenset(
    {
        "merge",
        "auto_merge",
        "automatic_merge",
        "deploy",
        "deployment",
        "automatic_deployment",
        "publish",
        "publication",
        "automatic_publication",
        "production_mutation",
        "production_database_mutation",
        "production_graph_mutation",
        "production_knowledge_graph_mutation",
        "taxonomy_activation",
        "credential_access",
        "spending",
        "force_push",
        "branch_delete",
        "delete_branch",
    }
)
REVIEW_REQUIRED_ACTIONS = frozenset(
    {
        "cross_repository",
        "external_send",
        "production_migration",
        "schema_activation",
        "create_branch",
        "create_commit",
        "push_branch",
        "open_pull_request",
    }
)
_TRUE_ACTION_FLAGS = frozenset({"1", "true", "yes", "on", "requested", "enabled"})
_ACTION_TOKEN_ALIASES = {
    "branch_deletion": "branch_delete",
}


class GovernanceDisposition(StrEnum):
    AUTOMATIC = "automatic"
    REVIEW_REQUIRED = "review_required"
    OWNER_ONLY = "owner_only"


class ValidationDisposition(StrEnum):
    ACCEPT = "accept"
    RETRY = "retry"
    REVIEW_REQUIRED = "review_required"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    disposition: GovernanceDisposition
    code: str
    priority: int

    @property
    def automatically_executable(self) -> bool:
        return self.disposition == GovernanceDisposition.AUTOMATIC


@dataclass(frozen=True, slots=True)
class ValidationDecision:
    disposition: ValidationDisposition
    code: str
    feedback: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.disposition == ValidationDisposition.ACCEPT


def _inputs(job: CalyxProgramJob) -> dict[str, Any]:
    if not job.input_json:
        return {}
    try:
        value = json.loads(job.input_json)
    except json.JSONDecodeError as exc:
        raise ValueError("PROGRAM_JOB_INPUT_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise TypeError("PROGRAM_JOB_INPUT_JSON_OBJECT_REQUIRED")
    return value


def _action_token(value: Any) -> str:
    """Canonicalize equivalent action spellings before governance comparison.

    Human-authored mission inputs may use spaces, hyphens, repeated separators, or
    mixed case (for example ``force-push`` or ``Production Migration``). Governance
    classification must not depend on superficial spelling choices.
    """

    token = str(value).strip().casefold()
    token = re.sub(r"[\s\-]+", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return _ACTION_TOKEN_ALIASES.get(token, token)


def _normalized_actions(value: Any) -> set[str]:
    actions: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = _action_token(key)
            if normalized_key in {
                "action",
                "operation",
                "action_class",
                "requested_action",
            }:
                if isinstance(item, str):
                    actions.add(_action_token(item))
            elif normalized_key in {
                "requested_capabilities",
                "capabilities",
                "actions",
            } and isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                actions.update(_action_token(entry) for entry in item)
            actions.update(_normalized_actions(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            actions.update(_normalized_actions(item))
    return {item for item in actions if item}


def _direct_requested_action_flags(value: Any) -> set[str]:
    """Detect explicit boolean/string action requests expressed as direct keys.

    Mission payloads are not required to encode intent only as ``action=merge`` or
    an ``actions`` list. A request such as ``{"merge": true}`` must not bypass the
    pre-claim governance hold. Only clearly enabled scalar flags are treated as
    action requests so evidence payloads like ``{"publication": {"doi": ...}}``
    are not misclassified as execution intent.
    """

    requested: set[str] = set()
    recognized = OWNER_ONLY_ACTIONS | REVIEW_REQUIRED_ACTIONS
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = _action_token(key)
            if normalized_key in recognized and (
                item is True
                or isinstance(item, str)
                and item.strip().casefold() in _TRUE_ACTION_FLAGS
            ):
                requested.add(normalized_key)
            requested.update(_direct_requested_action_flags(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            requested.update(_direct_requested_action_flags(item))
    return requested


class GovernanceAwarePrioritySelector:
    """Deterministically ranks only missions that remain inside autonomous authority."""

    def decision(self, job: CalyxProgramJob) -> GovernanceDecision:
        inputs = _inputs(job)
        raw_priority = inputs.get("priority", 100)
        if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
            raise TypeError("MISSION_PRIORITY_INTEGER_REQUIRED")
        priority = max(0, min(1000, raw_priority))
        governance = inputs.get("governance") or {}
        if governance and not isinstance(governance, Mapping):
            raise TypeError("MISSION_GOVERNANCE_OBJECT_REQUIRED")
        explicit = _action_token(governance.get("class", "")) if governance else ""
        if explicit in {"owner_only", "owner"}:
            return GovernanceDecision(
                GovernanceDisposition.OWNER_ONLY,
                "EXPLICIT_OWNER_ONLY",
                priority,
            )
        if explicit in {"review_required", "review"} or bool(
            governance.get("review_required", False)
        ):
            return GovernanceDecision(
                GovernanceDisposition.REVIEW_REQUIRED,
                "EXPLICIT_REVIEW_REQUIRED",
                priority,
            )
        actions = _normalized_actions(inputs) | _direct_requested_action_flags(inputs)
        owner_action = sorted(actions & OWNER_ONLY_ACTIONS)
        if owner_action:
            return GovernanceDecision(
                GovernanceDisposition.OWNER_ONLY,
                f"OWNER_ONLY_ACTION:{owner_action[0]}",
                priority,
            )
        review_action = sorted(actions & REVIEW_REQUIRED_ACTIONS)
        if review_action:
            return GovernanceDecision(
                GovernanceDisposition.REVIEW_REQUIRED,
                f"REVIEW_REQUIRED_ACTION:{review_action[0]}",
                priority,
            )
        return GovernanceDecision(
            GovernanceDisposition.AUTOMATIC,
            "AUTOMATICALLY_ADMISSIBLE",
            priority,
        )

    def order(
        self,
        jobs: Sequence[CalyxProgramJob],
        scheduler_rank: Mapping[str, int],
    ) -> list[CalyxProgramJob]:
        eligible: list[tuple[tuple[Any, ...], CalyxProgramJob]] = []
        for job in jobs:
            decision = self.decision(job)
            if not decision.automatically_executable:
                continue
            rank = scheduler_rank.get(job.program_job_id, 1_000_000)
            key = (
                decision.priority,
                job.attempt_count,
                rank,
                job.created_at,
                job.program_job_id,
            )
            eligible.append((key, job))
        eligible.sort(key=lambda item: item[0])
        return [job for _, job in eligible]


class MissionReceiptValidator:
    """Converts authoritative executor receipts into retry/review/accept decisions."""

    def validate(
        self,
        receipt: ExecutionReceipt,
        *,
        attempt_count: int,
        max_attempts: int,
    ) -> ValidationDecision:
        receipt.verify()
        output = dict(receipt.output)
        feedback = output.get("validation_errors") or output.get("validator_feedback") or []
        if isinstance(feedback, str):
            feedback = [feedback]
        if not isinstance(feedback, Sequence):
            feedback = ["VALIDATOR_FEEDBACK_INVALID"]
        normalized_feedback = tuple(str(item) for item in feedback if str(item).strip())

        if bool(output.get("requires_human_review")) or bool(
            output.get("governance_boundary")
        ):
            return ValidationDecision(
                ValidationDisposition.REVIEW_REQUIRED,
                "VALIDATOR_REQUIRES_HUMAN_REVIEW",
                normalized_feedback,
            )
        if receipt.state == ExecutionState.DELIVERED and normalized_feedback:
            disposition = (
                ValidationDisposition.DEAD_LETTER
                if attempt_count >= max_attempts
                else ValidationDisposition.RETRY
            )
            return ValidationDecision(
                disposition,
                "VALIDATOR_FEEDBACK_REJECTED_RESULT",
                normalized_feedback,
            )
        if receipt.state == ExecutionState.DELIVERED:
            return ValidationDecision(ValidationDisposition.ACCEPT, "VALIDATED")
        if receipt.blocker_code in {
            "PROHIBITED_CAPABILITY",
            "EXTERNAL_SIDE_EFFECT_EXECUTOR_NOT_ALLOWED",
        }:
            return ValidationDecision(
                ValidationDisposition.REVIEW_REQUIRED,
                receipt.blocker_code or "GOVERNANCE_BLOCKED",
                normalized_feedback,
            )
        if receipt.state == ExecutionState.CANCELLED:
            return ValidationDecision(
                ValidationDisposition.REVIEW_REQUIRED,
                "EXECUTION_CANCELLED",
                normalized_feedback,
            )
        disposition = (
            ValidationDisposition.DEAD_LETTER
            if attempt_count >= max_attempts
            else ValidationDisposition.RETRY
        )
        return ValidationDecision(
            disposition,
            receipt.blocker_code or "EXECUTION_NOT_DELIVERED",
            normalized_feedback,
        )
