"""Event-driven orchestration dispatcher for ORCHESTRATION-EVENT-DRIVEN-001.

Receives GitHub completion events (workflow_run, check_suite, pull_request sync)
and converts them into governed continuation or repair tasks without polling.

Safety invariants on every dispatch result:
- autonomous_merge = False
- deployment = False
- production_db_mutation = False
- owner_gate_preserved = True
- automatic_publication = False
- knowledge_graph_mutation = False
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = "oc-event-dispatcher/v1"

MAX_TRANSIENT_RETRIES = 3

_INFRASTRUCTURE_CONCLUSIONS = frozenset(
    {"cancelled", "timed_out", "action_required", "stale"}
)
_SUCCESS_CONCLUSIONS = frozenset({"success"})
_FAILURE_CONCLUSIONS = frozenset({"failure", "neutral"})
_TRANSIENT_CONCLUSIONS = frozenset({"skipped"})

_SUPPORTED_EVENT_KINDS = frozenset(
    {"workflow_run", "check_suite", "pull_request", "check_run"}
)


class EventKind(StrEnum):
    WORKFLOW_RUN = "workflow_run"
    CHECK_SUITE = "check_suite"
    PULL_REQUEST = "pull_request"
    CHECK_RUN = "check_run"


class EventOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    INFRASTRUCTURE = "infrastructure"
    STALE_HEAD = "stale_head"
    PENDING = "pending"
    TRANSIENT = "transient"


class DispatchAction(StrEnum):
    ENQUEUE_CONTINUATION = "enqueue_continuation"
    ENQUEUE_REPAIR = "enqueue_repair"
    FAIL_CLOSED_STALE_HEAD = "fail_closed_stale_head"
    HALT_INFRASTRUCTURE = "halt_infrastructure"
    AWAIT_COMPLETION = "await_completion"
    DEDUPLICATED_NO_OP = "deduplicated_no_op"
    RETRY_BACKOFF = "retry_backoff"
    HALT_RETRY_LIMIT = "halt_retry_limit"


@dataclass(frozen=True)
class EventKey:
    """Immutable identity for one completion event — used for deduplication."""

    repository: str
    pull_request_number: int
    branch: str
    head_sha: str
    run_id: str
    event_kind: str

    def __post_init__(self) -> None:
        if not self.repository:
            raise ValueError("EVENT_KEY_REPOSITORY_REQUIRED")
        if self.pull_request_number < 0:
            raise ValueError("EVENT_KEY_PR_NUMBER_INVALID")
        if not self.head_sha or len(self.head_sha) < 7:
            raise ValueError("EVENT_KEY_HEAD_SHA_INVALID")
        if not self.event_kind:
            raise ValueError("EVENT_KEY_EVENT_KIND_REQUIRED")

    @property
    def idempotency_key(self) -> str:
        raw = f"{self.repository}:{self.pull_request_number}:{self.head_sha}:{self.run_id}:{self.event_kind}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class ContinuationTask:
    """A next-safe-action task created in response to a completion event."""

    title: str
    task_kind: str
    pr_number: int
    head_sha: str
    branch: str
    repository: str
    outcome: EventOutcome
    idempotency_key: str
    failure_logs: str = ""
    retry_count: int = 0
    autonomous_merge: bool = False
    deployment: bool = False
    production_db_mutation: bool = False
    owner_gate_preserved: bool = True
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False

    def __post_init__(self) -> None:
        # Enforce safety invariants — these must never be True
        if self.autonomous_merge:
            raise PermissionError("CONTINUATION_AUTONOMOUS_MERGE_FORBIDDEN")
        if self.deployment:
            raise PermissionError("CONTINUATION_DEPLOYMENT_FORBIDDEN")
        if self.production_db_mutation:
            raise PermissionError("CONTINUATION_PRODUCTION_DB_MUTATION_FORBIDDEN")
        if not self.owner_gate_preserved:
            raise PermissionError("CONTINUATION_OWNER_GATE_MUST_BE_PRESERVED")
        if self.automatic_publication:
            raise PermissionError("CONTINUATION_AUTOMATIC_PUBLICATION_FORBIDDEN")
        if self.knowledge_graph_mutation:
            raise PermissionError("CONTINUATION_KG_MUTATION_FORBIDDEN")

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "task_kind": self.task_kind,
            "pr_number": self.pr_number,
            "head_sha": self.head_sha,
            "branch": self.branch,
            "repository": self.repository,
            "outcome": self.outcome.value,
            "idempotency_key": self.idempotency_key,
            "failure_logs": self.failure_logs,
            "retry_count": self.retry_count,
            "autonomous_merge": self.autonomous_merge,
            "deployment": self.deployment,
            "production_db_mutation": self.production_db_mutation,
            "owner_gate_preserved": self.owner_gate_preserved,
            "automatic_publication": self.automatic_publication,
            "knowledge_graph_mutation": self.knowledge_graph_mutation,
        }


@dataclass(frozen=True)
class DispatchResult:
    """Result of processing one completion event."""

    action: DispatchAction
    event_key: EventKey
    outcome: EventOutcome
    task: ContinuationTask | None = None
    detail: str = ""
    retry_count: int = 0
    autonomous_merge: bool = False
    deployment: bool = False
    production_db_mutation: bool = False
    owner_gate_preserved: bool = True
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False

    def __post_init__(self) -> None:
        if self.autonomous_merge:
            raise PermissionError("DISPATCH_AUTONOMOUS_MERGE_FORBIDDEN")
        if self.deployment:
            raise PermissionError("DISPATCH_DEPLOYMENT_FORBIDDEN")
        if not self.owner_gate_preserved:
            raise PermissionError("DISPATCH_OWNER_GATE_MUST_BE_PRESERVED")
        if self.automatic_publication:
            raise PermissionError("DISPATCH_AUTOMATIC_PUBLICATION_FORBIDDEN")
        if self.knowledge_graph_mutation:
            raise PermissionError("DISPATCH_KG_MUTATION_FORBIDDEN")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "outcome": self.outcome.value,
            "event_key": {
                "repository": self.event_key.repository,
                "pull_request_number": self.event_key.pull_request_number,
                "branch": self.event_key.branch,
                "head_sha": self.event_key.head_sha,
                "run_id": self.event_key.run_id,
                "event_kind": self.event_key.event_kind,
                "idempotency_key": self.event_key.idempotency_key,
            },
            "task": self.task.to_dict() if self.task else None,
            "detail": self.detail,
            "retry_count": self.retry_count,
            "autonomous_merge": self.autonomous_merge,
            "deployment": self.deployment,
            "production_db_mutation": self.production_db_mutation,
            "owner_gate_preserved": self.owner_gate_preserved,
            "automatic_publication": self.automatic_publication,
            "knowledge_graph_mutation": self.knowledge_graph_mutation,
        }


class EventDeduplicator:
    """In-memory deduplication store keyed on EventKey.idempotency_key.

    In production this would be backed by CalyxJob or a Redis set. The in-memory
    implementation is sufficient for unit tests and canary proofs; production
    integrators should wrap with a persistent store.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_duplicate(self, key: EventKey) -> bool:
        return key.idempotency_key in self._seen

    def mark_seen(self, key: EventKey) -> None:
        self._seen.add(key.idempotency_key)

    def clear(self) -> None:
        self._seen.clear()


def bind_event_key(payload: dict[str, Any], event_kind: str) -> EventKey:
    """Extract and validate the exact binding fields from a raw GitHub event payload."""
    if event_kind not in _SUPPORTED_EVENT_KINDS:
        raise ValueError(f"EVENT_KIND_UNSUPPORTED: {event_kind!r}")

    if event_kind == "workflow_run":
        run = payload.get("workflow_run", {})
        repo = payload.get("repository", {}).get("full_name", "")
        branch = str(run.get("head_branch") or "")
        head_sha = str(run.get("head_sha") or "")
        run_id = str(run.get("id") or "")
        pr_list = run.get("pull_requests") or []
        pr_number = int(pr_list[0].get("number", 0)) if pr_list else 0

    elif event_kind == "check_suite":
        suite = payload.get("check_suite", {})
        repo = payload.get("repository", {}).get("full_name", "")
        branch = str(suite.get("head_branch") or "")
        head_sha = str(suite.get("head_sha") or "")
        run_id = str(suite.get("id") or "")
        pr_list = suite.get("pull_requests") or []
        pr_number = int(pr_list[0].get("number", 0)) if pr_list else 0

    elif event_kind == "pull_request":
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {}).get("full_name", "")
        branch = str(pr.get("head", {}).get("ref") or "")
        head_sha = str(pr.get("head", {}).get("sha") or "")
        run_id = f"pr-{pr.get('number', 0)}"
        pr_number = int(pr.get("number") or 0)

    elif event_kind == "check_run":
        run = payload.get("check_run", {})
        repo = payload.get("repository", {}).get("full_name", "")
        branch = str(run.get("check_suite", {}).get("head_branch") or "")
        head_sha = str(run.get("head_sha") or "")
        run_id = str(run.get("id") or "")
        pr_list = run.get("pull_requests") or []
        pr_number = int(pr_list[0].get("number", 0)) if pr_list else 0

    else:
        raise ValueError(f"EVENT_KIND_UNSUPPORTED: {event_kind!r}")

    return EventKey(
        repository=repo,
        pull_request_number=pr_number,
        branch=branch,
        head_sha=head_sha,
        run_id=run_id,
        event_kind=event_kind,
    )


def classify_workflow_run_event(payload: dict[str, Any]) -> EventOutcome:
    """Classify a workflow_run or check_suite payload into an EventOutcome."""
    run = payload.get("workflow_run") or payload.get("check_suite") or {}
    status = str(run.get("status") or "").strip()
    conclusion = str(run.get("conclusion") or "").strip() or None

    if status != "completed":
        return EventOutcome.PENDING

    if conclusion in _SUCCESS_CONCLUSIONS:
        return EventOutcome.SUCCESS
    if conclusion in _INFRASTRUCTURE_CONCLUSIONS:
        return EventOutcome.INFRASTRUCTURE
    if conclusion in _TRANSIENT_CONCLUSIONS:
        return EventOutcome.TRANSIENT
    if conclusion in _FAILURE_CONCLUSIONS:
        return EventOutcome.FAILURE

    return EventOutcome.FAILURE


def validate_head_binding(event_key: EventKey, expected_head_sha: str) -> bool:
    """Return True if event_key.head_sha matches expected; False means stale."""
    if not expected_head_sha:
        return True
    return event_key.head_sha == expected_head_sha


def create_continuation_task(event_key: EventKey, outcome: EventOutcome) -> ContinuationTask:
    """Create a governed next-safe-action continuation task from a success event."""
    title = (
        f"[AUTO] Verify/continue PR#{event_key.pull_request_number} "
        f"after {event_key.event_kind} success on {event_key.head_sha[:12]}"
    )
    return ContinuationTask(
        title=title,
        task_kind="continuation",
        pr_number=event_key.pull_request_number,
        head_sha=event_key.head_sha,
        branch=event_key.branch,
        repository=event_key.repository,
        outcome=outcome,
        idempotency_key=event_key.idempotency_key,
    )


def create_repair_task(
    event_key: EventKey,
    failure_logs: str,
    *,
    retry_count: int = 0,
) -> ContinuationTask | None:
    """Create a bounded repair task. Returns None if retry ceiling exceeded."""
    if retry_count >= MAX_TRANSIENT_RETRIES:
        return None
    title = (
        f"[AUTO] Repair PR#{event_key.pull_request_number} "
        f"after {event_key.event_kind} failure on {event_key.head_sha[:12]}"
    )
    return ContinuationTask(
        title=title,
        task_kind="repair",
        pr_number=event_key.pull_request_number,
        head_sha=event_key.head_sha,
        branch=event_key.branch,
        repository=event_key.repository,
        outcome=EventOutcome.FAILURE,
        idempotency_key=event_key.idempotency_key,
        failure_logs=failure_logs[:4096],
        retry_count=retry_count,
    )


def dispatch_event(
    payload: dict[str, Any],
    event_kind: str,
    deduplicator: EventDeduplicator,
    *,
    expected_head_sha: str = "",
    failure_logs: str = "",
    retry_count: int = 0,
) -> DispatchResult:
    """Core dispatcher: bind event, dedup, classify, create task.

    This is the governed entry point for all CI completion events. It enforces:
    - Exact-head binding (stale SHA → fail-closed, no continuation)
    - Deduplication (replayed delivery → no-op, no duplicate task)
    - Owner-gate preservation (merge/deploy/publish never automated)
    - Bounded retry (stop at MAX_TRANSIENT_RETRIES)
    """
    event_key = bind_event_key(payload, event_kind)

    # Deduplication: replay → no-op
    if deduplicator.is_duplicate(event_key):
        return DispatchResult(
            action=DispatchAction.DEDUPLICATED_NO_OP,
            event_key=event_key,
            outcome=EventOutcome.PENDING,
            detail="Replayed delivery; idempotency_key already processed.",
        )

    # Exact-head binding: stale SHA → fail-closed
    if expected_head_sha and not validate_head_binding(event_key, expected_head_sha):
        deduplicator.mark_seen(event_key)
        return DispatchResult(
            action=DispatchAction.FAIL_CLOSED_STALE_HEAD,
            event_key=event_key,
            outcome=EventOutcome.STALE_HEAD,
            detail=(
                f"Head SHA mismatch: event has {event_key.head_sha!r},"
                f" expected {expected_head_sha!r}. Reconcile before continuing."
            ),
        )

    outcome = classify_workflow_run_event(payload)

    if outcome == EventOutcome.PENDING:
        deduplicator.mark_seen(event_key)
        return DispatchResult(
            action=DispatchAction.AWAIT_COMPLETION,
            event_key=event_key,
            outcome=outcome,
            detail="Workflow not yet completed; awaiting conclusion.",
        )

    if outcome == EventOutcome.SUCCESS:
        task = create_continuation_task(event_key, outcome)
        deduplicator.mark_seen(event_key)
        return DispatchResult(
            action=DispatchAction.ENQUEUE_CONTINUATION,
            event_key=event_key,
            outcome=outcome,
            task=task,
            detail="CI success: continuation task enqueued immediately.",
        )

    if outcome == EventOutcome.INFRASTRUCTURE:
        deduplicator.mark_seen(event_key)
        return DispatchResult(
            action=DispatchAction.HALT_INFRASTRUCTURE,
            event_key=event_key,
            outcome=outcome,
            detail="Infrastructure failure (cancelled/timed_out/action_required/stale). Not repaired; requires owner review.",
        )

    if outcome == EventOutcome.TRANSIENT:
        if retry_count >= MAX_TRANSIENT_RETRIES:
            deduplicator.mark_seen(event_key)
            return DispatchResult(
                action=DispatchAction.HALT_RETRY_LIMIT,
                event_key=event_key,
                outcome=outcome,
                retry_count=retry_count,
                detail=f"Transient retry ceiling reached ({MAX_TRANSIENT_RETRIES}). Requires owner review.",
            )
        return DispatchResult(
            action=DispatchAction.RETRY_BACKOFF,
            event_key=event_key,
            outcome=outcome,
            retry_count=retry_count,
            detail=f"Transient outcome; retry {retry_count + 1}/{MAX_TRANSIENT_RETRIES} permitted.",
        )

    # FAILURE
    task = create_repair_task(event_key, failure_logs, retry_count=retry_count)
    deduplicator.mark_seen(event_key)
    if task is None:
        return DispatchResult(
            action=DispatchAction.HALT_RETRY_LIMIT,
            event_key=event_key,
            outcome=outcome,
            retry_count=retry_count,
            detail=f"Repair ceiling reached ({MAX_TRANSIENT_RETRIES}). Requires owner review.",
        )
    return DispatchResult(
        action=DispatchAction.ENQUEUE_REPAIR,
        event_key=event_key,
        outcome=outcome,
        task=task,
        retry_count=retry_count,
        detail="CI failure: deduped repair task created with failure evidence.",
    )


def get_dispatcher_manifest() -> dict[str, Any]:
    """Machine-readable summary of dispatcher capabilities and invariants."""
    return {
        "schema_version": SCHEMA_VERSION,
        "supported_event_kinds": sorted(_SUPPORTED_EVENT_KINDS),
        "max_transient_retries": MAX_TRANSIENT_RETRIES,
        "dispatch_actions": [a.value for a in DispatchAction],
        "event_outcomes": [o.value for o in EventOutcome],
        "invariants": {
            "autonomous_merge": False,
            "deployment": False,
            "production_db_mutation": False,
            "owner_gate_preserved": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
        "deduplication": "idempotency_key = sha256(repo:pr:head_sha:run_id:event_kind)[:32]",
        "head_binding": "stale_sha_fails_closed",
        "retry_ceiling": f"HALT after {MAX_TRANSIENT_RETRIES} transient outcomes",
    }


def serialize_manifest_as_json() -> str:
    return json.dumps(get_dispatcher_manifest(), indent=2, sort_keys=True)
