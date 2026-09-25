from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.calyx_engineering.event_dispatcher import MAX_TRANSIENT_RETRIES


class CompletionEventKind(StrEnum):
    WORKFLOW_RUN = "workflow_run"
    CHECK_RUN = "check_run"
    CHECK_SUITE = "check_suite"
    PULL_REQUEST = "pull_request"
    ISSUE_COMMENT = "issue_comment"


class ContinuationAction(StrEnum):
    NO_OP_REPLAY = "no_op_replay"
    RECONCILE_STALE_HEAD = "reconcile_stale_head"
    CONTINUE_PROVIDER_FREE = "continue_provider_free"
    PREPARE_REPAIR = "prepare_repair"
    PARK_PROVIDER_REQUIRED = "park_provider_required"
    PARK_INFRASTRUCTURE = "park_infrastructure"
    OWNER_GATE = "owner_gate"
    AWAIT_TERMINAL_EVENT = "await_terminal_event"


@dataclass(frozen=True, slots=True)
class CompletionEvent:
    repository: str
    kind: CompletionEventKind
    event_id: str
    head_sha: str
    conclusion: str | None
    branch: str | None = None
    workflow_run_id: str | None = None
    check_run_id: str | None = None
    issue_number: int | None = None
    pull_request_number: int | None = None
    program_job_id: str | None = None
    mission_id: str | None = None

    @property
    def material_fingerprint(self) -> str:
        material = {
            "branch": self.branch,
            "check_run_id": self.check_run_id,
            "conclusion": self.conclusion,
            "event_id": self.event_id,
            "head_sha": self.head_sha,
            "issue_number": self.issue_number,
            "kind": self.kind.value,
            "mission_id": self.mission_id,
            "program_job_id": self.program_job_id,
            "pull_request_number": self.pull_request_number,
            "repository": self.repository,
            "workflow_run_id": self.workflow_run_id,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ContinuationPolicy:
    no_api_mode: bool = True
    owner_gate_required: bool = False
    provider_required: bool = False
    repair_attempt_count: int = 0
    max_repair_attempts: int = MAX_TRANSIENT_RETRIES

    def __post_init__(self) -> None:
        if self.repair_attempt_count < 0:
            raise ValueError("REPAIR_ATTEMPT_COUNT_INVALID")
        if self.max_repair_attempts <= 0:
            raise ValueError("MAX_REPAIR_ATTEMPTS_INVALID")


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    action: ContinuationAction
    fingerprint: str
    reason: str
    side_effects_authorized: bool = False


class EventNormalizationError(ValueError):
    pass


def normalize_completion_event(payload: Mapping[str, object]) -> CompletionEvent:
    """Normalize a repository-native completion signal without causing side effects.

    The caller supplies already-validated GitHub metadata. This function deliberately
    does not fetch GitHub, dispatch an agent, or mutate a queue. Missing exact-head
    identity fails closed so a continuation can never be admitted from ambiguous
    repository state.
    """

    repository = _required_text(payload, "repository")
    kind_text = _required_text(payload, "kind")
    event_id = _required_text(payload, "event_id")
    head_sha = _required_text(payload, "head_sha")
    try:
        kind = CompletionEventKind(kind_text)
    except ValueError as exc:
        raise EventNormalizationError("UNSUPPORTED_COMPLETION_EVENT_KIND") from exc

    return CompletionEvent(
        repository=repository,
        kind=kind,
        event_id=event_id,
        head_sha=head_sha,
        conclusion=_optional_text(payload, "conclusion"),
        branch=_optional_text(payload, "branch"),
        workflow_run_id=_optional_text(payload, "workflow_run_id"),
        check_run_id=_optional_text(payload, "check_run_id"),
        issue_number=_optional_positive_int(payload, "issue_number"),
        pull_request_number=_optional_positive_int(payload, "pull_request_number"),
        program_job_id=_optional_text(payload, "program_job_id"),
        mission_id=_optional_text(payload, "mission_id"),
    )


def reconcile_completion_event(
    event: CompletionEvent,
    *,
    current_head_sha: str,
    seen_fingerprints: frozenset[str] = frozenset(),
    policy: ContinuationPolicy | None = None,
) -> ContinuationDecision:
    """Classify the next bounded action for one exact completion event.

    Decisions are descriptive only. Provider dispatch, GitHub mutation, merge,
    deployment, publication, and production mutation remain outside this module.
    """

    active_policy = policy if policy is not None else ContinuationPolicy()
    fingerprint = event.material_fingerprint
    if fingerprint in seen_fingerprints:
        return ContinuationDecision(
            action=ContinuationAction.NO_OP_REPLAY,
            fingerprint=fingerprint,
            reason="UNCHANGED_EVENT_ALREADY_RECONCILED",
        )

    if not current_head_sha or event.head_sha != current_head_sha:
        return ContinuationDecision(
            action=ContinuationAction.RECONCILE_STALE_HEAD,
            fingerprint=fingerprint,
            reason="EVENT_HEAD_DOES_NOT_MATCH_CURRENT_HEAD",
        )

    if active_policy.owner_gate_required:
        return ContinuationDecision(
            action=ContinuationAction.OWNER_GATE,
            fingerprint=fingerprint,
            reason="OWNER_GATED_CONTINUATION",
        )

    conclusion = (event.conclusion or "").lower()
    if conclusion in {"", "queued", "in_progress", "requested", "waiting", "pending"}:
        return ContinuationDecision(
            action=ContinuationAction.AWAIT_TERMINAL_EVENT,
            fingerprint=fingerprint,
            reason="EVENT_NOT_TERMINAL",
        )
    if conclusion in {"cancelled", "timed_out", "action_required", "stale"}:
        return ContinuationDecision(
            action=ContinuationAction.PARK_INFRASTRUCTURE,
            fingerprint=fingerprint,
            reason=f"CI_INFRASTRUCTURE_BLOCKED:{conclusion}",
        )
    if conclusion == "success":
        if active_policy.provider_required:
            return _park_provider_required(fingerprint, active_policy)
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_PROVIDER_FREE,
            fingerprint=fingerprint,
            reason="TERMINAL_EVENT_READY_FOR_DETERMINISTIC_RECONCILIATION",
        )
    if conclusion in {"neutral", "skipped"}:
        return ContinuationDecision(
            action=ContinuationAction.OWNER_GATE,
            fingerprint=fingerprint,
            reason=f"NON_SUCCESS_TERMINAL:{conclusion}",
        )
    if conclusion in {"failure", "startup_failure"}:
        if active_policy.repair_attempt_count >= active_policy.max_repair_attempts:
            return ContinuationDecision(
                action=ContinuationAction.OWNER_GATE,
                fingerprint=fingerprint,
                reason=(
                    "REPAIR_ATTEMPT_LIMIT_REACHED:"
                    f"{active_policy.repair_attempt_count}"
                ),
            )
        if active_policy.provider_required:
            return _park_provider_required(fingerprint, active_policy)
        return ContinuationDecision(
            action=ContinuationAction.PREPARE_REPAIR,
            fingerprint=fingerprint,
            reason=f"TERMINAL_FAILURE:{conclusion}",
        )
    return ContinuationDecision(
        action=ContinuationAction.OWNER_GATE,
        fingerprint=fingerprint,
        reason=f"UNKNOWN_EVENT_CONCLUSION:{conclusion}",
    )


def _park_provider_required(
    fingerprint: str, policy: ContinuationPolicy
) -> ContinuationDecision:
    return ContinuationDecision(
        action=ContinuationAction.PARK_PROVIDER_REQUIRED,
        fingerprint=fingerprint,
        reason=(
            "NO_API_PROVIDER_CONTINUATION_PARKED"
            if policy.no_api_mode
            else "PROVIDER_CONTINUATION_REQUIRES_SEPARATE_AUTHORIZATION"
        ),
    )


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise EventNormalizationError(f"{key.upper()}_REQUIRED")
    return value


def _optional_text(payload: Mapping[str, object], key: str) -> str | None:
    raw = payload.get(key)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _optional_positive_int(payload: Mapping[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise EventNormalizationError(f"{key.upper()}_INVALID") from exc
    if value <= 0:
        raise EventNormalizationError(f"{key.upper()}_INVALID")
    return value
