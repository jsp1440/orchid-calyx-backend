"""Provider-free workflow reconstruction over the canonical SCI-OBS ledger.

This module interprets bounded workflow-intelligence-v1 metadata carried in
sci-obs-event-v1 extensions. It never writes observations or authoritative
scientific state. Invalid metadata and illegal transitions fail closed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .store import ObservationStore

CONTRACT_VERSION = "workflow-intelligence-v1"
MAX_REFERENCE_COUNT = 16

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
_REFERENCE = re.compile(
    r"^(?:event|artifact|review|issue|commit):[A-Za-z0-9][A-Za-z0-9._:/-]{0,179}$"
)


class WorkflowValidationError(ValueError):
    """Raised when workflow metadata or its event sequence is unsafe."""


class WorkflowType(str, Enum):
    SOURCE_INGESTION = "source_ingestion"
    TAXONOMY_RECONCILIATION = "taxonomy_reconciliation"
    SCIENTIFIC_VERIFICATION = "scientific_verification"
    CALYX_MISSION = "calyx_mission"
    BUILD_CI_VALIDATION = "build_ci_validation"
    GOVERNED_AGENT_TASK = "governed_agent_task"


class WorkflowStage(str, Enum):
    QUEUE = "queue"
    ACQUIRE = "acquire"
    NORMALIZE = "normalize"
    RECONCILE = "reconcile"
    VERIFY = "verify"
    EXECUTE = "execute"
    VALIDATE = "validate"
    REVIEW = "review"
    COMPLETE = "complete"


class WorkflowState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkflowActorType(str, Enum):
    SERVICE = "service"
    WORKER = "worker"
    AGENT = "agent"
    HUMAN = "human"
    CI = "ci"


_ALLOWED_TRANSITIONS: dict[WorkflowState | None, frozenset[WorkflowState]] = {
    None: frozenset({WorkflowState.QUEUED, WorkflowState.RUNNING}),
    WorkflowState.QUEUED: frozenset(
        {WorkflowState.RUNNING, WorkflowState.BLOCKED, WorkflowState.CANCELLED}
    ),
    WorkflowState.RUNNING: frozenset(
        {
            WorkflowState.RUNNING,
            WorkflowState.BLOCKED,
            WorkflowState.REVIEW_REQUIRED,
            WorkflowState.FAILED,
            WorkflowState.COMPLETED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.BLOCKED: frozenset(
        {
            WorkflowState.RUNNING,
            WorkflowState.REVIEW_REQUIRED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.REVIEW_REQUIRED: frozenset(
        {WorkflowState.RUNNING, WorkflowState.BLOCKED, WorkflowState.COMPLETED}
    ),
    WorkflowState.FAILED: frozenset(
        {WorkflowState.RUNNING, WorkflowState.BLOCKED, WorkflowState.CANCELLED}
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.CANCELLED: frozenset(),
}

_METADATA_KEYS = frozenset(
    {
        "contract_version",
        "workflow_id",
        "workflow_type",
        "stage",
        "previous_state",
        "resulting_state",
        "actor_type",
        "actor_id",
        "retry_count",
        "evidence_refs",
        "blocker_refs",
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowObservation:
    workflow_id: str
    workflow_type: WorkflowType
    stage: WorkflowStage
    previous_state: WorkflowState | None
    resulting_state: WorkflowState
    actor_type: WorkflowActorType
    actor_id: str
    retry_count: int
    evidence_refs: tuple[str, ...]
    blocker_refs: tuple[str, ...]


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise WorkflowValidationError(f"{name} is not a bounded safe identifier")
    return value


def _references(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_REFERENCE_COUNT:
        raise WorkflowValidationError(f"{name} must be a bounded list")
    result: list[str] = []
    for reference in value:
        if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
            raise WorkflowValidationError(f"{name} contains an unsafe reference")
        if reference not in result:
            result.append(reference)
    return tuple(result)


def workflow_metadata(
    *,
    workflow_id: str,
    workflow_type: WorkflowType,
    stage: WorkflowStage,
    previous_state: WorkflowState | None,
    resulting_state: WorkflowState,
    actor_type: WorkflowActorType,
    actor_id: str,
    retry_count: int = 0,
    evidence_refs: tuple[str, ...] = (),
    blocker_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build validated, schema-bounded metadata for one observation event."""

    payload = {
        "contract_version": CONTRACT_VERSION,
        "workflow_id": workflow_id,
        "workflow_type": workflow_type.value,
        "stage": stage.value,
        "previous_state": previous_state.value if previous_state else None,
        "resulting_state": resulting_state.value,
        "actor_type": actor_type.value,
        "actor_id": actor_id,
        "retry_count": retry_count,
        "evidence_refs": list(evidence_refs),
        "blocker_refs": list(blocker_refs),
    }
    parse_workflow_metadata({"extensions": {"workflow": payload}})
    return {"workflow": payload}


def parse_workflow_metadata(event: Mapping[str, Any]) -> WorkflowObservation:
    """Parse one SCI-OBS event's workflow metadata, rejecting unknown fields."""

    extensions = event.get("extensions")
    if not isinstance(extensions, Mapping):
        raise WorkflowValidationError("extensions must be an object")
    raw = extensions.get("workflow")
    if not isinstance(raw, Mapping):
        raise WorkflowValidationError("workflow metadata is required")
    unknown = set(raw) - _METADATA_KEYS
    if unknown:
        raise WorkflowValidationError(
            f"workflow metadata contains unsupported fields: {sorted(unknown)}"
        )
    if raw.get("contract_version") != CONTRACT_VERSION:
        raise WorkflowValidationError("unsupported workflow metadata version")

    try:
        workflow_type = WorkflowType(raw.get("workflow_type"))
        stage = WorkflowStage(raw.get("stage"))
        previous_raw = raw.get("previous_state")
        previous_state = WorkflowState(previous_raw) if previous_raw is not None else None
        resulting_state = WorkflowState(raw.get("resulting_state"))
        actor_type = WorkflowActorType(raw.get("actor_type"))
    except (TypeError, ValueError) as exc:
        raise WorkflowValidationError("workflow metadata contains an unsupported enum") from exc

    retry_count = raw.get("retry_count")
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        raise WorkflowValidationError("retry_count must be an integer")
    if retry_count < 0 or retry_count > 100:
        raise WorkflowValidationError("retry_count is outside the bounded range")

    return WorkflowObservation(
        workflow_id=_identifier(raw.get("workflow_id"), "workflow_id"),
        workflow_type=workflow_type,
        stage=stage,
        previous_state=previous_state,
        resulting_state=resulting_state,
        actor_type=actor_type,
        actor_id=_identifier(raw.get("actor_id"), "actor_id"),
        retry_count=retry_count,
        evidence_refs=_references(raw.get("evidence_refs"), "evidence_refs"),
        blocker_refs=_references(raw.get("blocker_refs"), "blocker_refs"),
    )


def _validate_transition(
    prior: WorkflowState | None,
    observation: WorkflowObservation,
) -> None:
    if observation.previous_state is not prior:
        raise WorkflowValidationError("previous_state does not match persisted workflow state")
    if observation.resulting_state not in _ALLOWED_TRANSITIONS[prior]:
        previous = prior.value if prior else "not_started"
        raise WorkflowValidationError(
            f"illegal workflow transition: {previous}->{observation.resulting_state.value}"
        )


class WorkflowReconstructor:
    """Read-only reconstruction and deterministic finding generation."""

    def __init__(self, store: ObservationStore) -> None:
        self._store = store

    def reconstruct(
        self,
        correlation_id: str,
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        events = self._store.by_correlation(correlation_id)
        observations: list[tuple[dict[str, Any], WorkflowObservation]] = []
        for event in events:
            try:
                metadata = parse_workflow_metadata(event)
            except WorkflowValidationError:
                continue
            if workflow_id is None or metadata.workflow_id == workflow_id:
                observations.append((event, metadata))

        if not observations:
            raise WorkflowValidationError("no workflow observations found")

        expected_id = observations[0][1].workflow_id
        expected_type = observations[0][1].workflow_type
        state: WorkflowState | None = None
        stages: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        blocker_refs: list[str] = []
        seen_stages: set[WorkflowStage] = set()
        rework_count = 0
        retry_count = 0

        for event, observation in observations:
            if (
                observation.workflow_id != expected_id
                or observation.workflow_type is not expected_type
            ):
                raise WorkflowValidationError(
                    "correlation contains conflicting workflow identity"
                )
            _validate_transition(state, observation)
            if observation.stage in seen_stages:
                rework_count += 1
            seen_stages.add(observation.stage)
            state = observation.resulting_state
            retry_count = max(retry_count, observation.retry_count)
            for reference in observation.evidence_refs:
                if reference not in evidence_refs:
                    evidence_refs.append(reference)
            for reference in observation.blocker_refs:
                if reference not in blocker_refs:
                    blocker_refs.append(reference)
            stages.append(
                {
                    "event_id": event.get("event_id"),
                    "sequence": event.get("sequence"),
                    "stage": observation.stage.value,
                    "previous_state": (
                        observation.previous_state.value
                        if observation.previous_state
                        else None
                    ),
                    "resulting_state": observation.resulting_state.value,
                    "actor_type": observation.actor_type.value,
                    "actor_id": observation.actor_id,
                    "retry_count": observation.retry_count,
                    "evidence_refs": list(observation.evidence_refs),
                    "blocker_refs": list(observation.blocker_refs),
                }
            )

        findings: list[dict[str, Any]] = []
        if state is WorkflowState.COMPLETED and not evidence_refs:
            findings.append(
                {
                    "rule_version": CONTRACT_VERSION,
                    "reason_code": "MISSING_COMPLETION_EVIDENCE",
                    "inputs": {
                        "resulting_state": state.value,
                        "evidence_reference_count": 0,
                    },
                    "requires_human_review": True,
                }
            )
        if retry_count >= 2:
            findings.append(
                {
                    "rule_version": CONTRACT_VERSION,
                    "reason_code": "EXCESSIVE_RETRY",
                    "inputs": {"retry_count": retry_count, "threshold": 2},
                    "requires_human_review": True,
                }
            )

        return {
            "contract_version": CONTRACT_VERSION,
            "workflow_id": expected_id,
            "workflow_type": expected_type.value,
            "correlation_id": correlation_id,
            "current_state": state.value if state else None,
            "stages": stages,
            "retry_count": retry_count,
            "rework_count": rework_count,
            "evidence_refs": evidence_refs,
            "blocker_refs": blocker_refs,
            "findings": findings,
            "authoritative_state_mutated": False,
            "publication_authority": False,
        }
