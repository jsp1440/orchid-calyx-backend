from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.calyx_orchestrator.event_continuation import (
    CompletionEvent,
    ContinuationAction,
    ContinuationDecision,
    ContinuationPolicy,
    reconcile_completion_event,
)
from app.calyx_orchestrator.factory_policy import (
    FactoryAction,
    FactoryDecision,
    MissionStatus,
    ValidationEvidence,
    WorkIntent,
    evaluate_factory_gate,
)


class FactoryBridgeAction(StrEnum):
    NO_OP = "no_op"
    WAIT = "wait"
    RECONCILE = "reconcile"
    REQUIRE_CHECKER = "require_checker"
    AUTO_INTEGRATE = "auto_integrate"
    PREPARE_REPAIR = "prepare_repair"
    PARK_PROVIDER_REQUIRED = "park_provider_required"
    PARK_INFRASTRUCTURE = "park_infrastructure"
    OWNER_GATE = "owner_gate"


@dataclass(frozen=True, slots=True)
class FactoryBridgeDecision:
    action: FactoryBridgeAction
    mission_status: MissionStatus
    reason: str
    continuation: ContinuationDecision
    factory: FactoryDecision | None = None
    integration_authorized: bool = False


def route_completion_to_factory(
    event: CompletionEvent,
    *,
    current_head_sha: str,
    intent: WorkIntent,
    evidence: ValidationEvidence,
    seen_fingerprints: frozenset[str] = frozenset(),
    continuation_policy: ContinuationPolicy | None = None,
    no_api_mode: bool = True,
) -> FactoryBridgeDecision:
    """Compose Queue Bridge reconciliation with the Software Factory gate.

    The function is deterministic and side-effect free. It creates one canonical
    next-action decision for schedulers/workflows so Queue Bridge, checker routing,
    and risk policy cannot silently disagree.
    """

    continuation = reconcile_completion_event(
        event,
        current_head_sha=current_head_sha,
        seen_fingerprints=seen_fingerprints,
        policy=continuation_policy,
    )

    if continuation.action is ContinuationAction.NO_OP_REPLAY:
        return _decision(
            FactoryBridgeAction.NO_OP,
            MissionStatus.DONE,
            continuation.reason,
            continuation,
        )

    if continuation.action is ContinuationAction.RECONCILE_STALE_HEAD:
        return _decision(
            FactoryBridgeAction.RECONCILE,
            MissionStatus.VALIDATING,
            continuation.reason,
            continuation,
        )

    if continuation.action is ContinuationAction.AWAIT_TERMINAL_EVENT:
        return _decision(
            FactoryBridgeAction.WAIT,
            MissionStatus.RUNNING,
            continuation.reason,
            continuation,
        )

    if continuation.action is ContinuationAction.PARK_INFRASTRUCTURE:
        return _decision(
            FactoryBridgeAction.PARK_INFRASTRUCTURE,
            MissionStatus.BLOCKED,
            continuation.reason,
            continuation,
        )

    if continuation.action is ContinuationAction.PARK_PROVIDER_REQUIRED:
        return _decision(
            FactoryBridgeAction.PARK_PROVIDER_REQUIRED,
            MissionStatus.BLOCKED,
            continuation.reason,
            continuation,
        )

    if continuation.action is ContinuationAction.OWNER_GATE:
        return _decision(
            FactoryBridgeAction.OWNER_GATE,
            MissionStatus.BLOCKED,
            continuation.reason,
            continuation,
        )

    if continuation.action is ContinuationAction.PREPARE_REPAIR:
        return _decision(
            FactoryBridgeAction.PREPARE_REPAIR,
            MissionStatus.RUNNING,
            continuation.reason,
            continuation,
        )

    if continuation.action is not ContinuationAction.CONTINUE_PROVIDER_FREE:
        return _decision(
            FactoryBridgeAction.OWNER_GATE,
            MissionStatus.BLOCKED,
            f"UNMAPPED_CONTINUATION:{continuation.action.value}",
            continuation,
        )

    identity_error = _identity_error(event, current_head_sha, intent)
    if identity_error is not None:
        return _decision(
            FactoryBridgeAction.RECONCILE,
            MissionStatus.VALIDATING,
            identity_error,
            continuation,
        )

    factory = evaluate_factory_gate(intent, evidence, no_api_mode=no_api_mode)

    if factory.action is FactoryAction.AUTO_INTEGRATE:
        return _decision(
            FactoryBridgeAction.AUTO_INTEGRATE,
            MissionStatus.VALIDATING,
            factory.reason,
            continuation,
            factory,
            integration_authorized=True,
        )

    if factory.action is FactoryAction.REQUIRE_CHECKER:
        return _decision(
            FactoryBridgeAction.REQUIRE_CHECKER,
            MissionStatus.VALIDATING,
            factory.reason,
            continuation,
            factory,
        )

    if factory.action is FactoryAction.PREPARE_REPAIR:
        return _decision(
            FactoryBridgeAction.PREPARE_REPAIR,
            MissionStatus.RUNNING,
            factory.reason,
            continuation,
            factory,
        )

    if factory.action is FactoryAction.PARK_PROVIDER_REQUIRED:
        return _decision(
            FactoryBridgeAction.PARK_PROVIDER_REQUIRED,
            MissionStatus.BLOCKED,
            factory.reason,
            continuation,
            factory,
        )

    return _decision(
        FactoryBridgeAction.OWNER_GATE,
        MissionStatus.BLOCKED,
        factory.reason,
        continuation,
        factory,
    )


def _identity_error(
    event: CompletionEvent, current_head_sha: str, intent: WorkIntent
) -> str | None:
    if intent.repository != event.repository:
        return "FACTORY_REPOSITORY_IDENTITY_MISMATCH"
    if not current_head_sha or intent.head_sha != current_head_sha:
        return "FACTORY_HEAD_IDENTITY_MISMATCH"
    if event.issue_number is not None and intent.issue_number != event.issue_number:
        return "FACTORY_ISSUE_IDENTITY_MISMATCH"
    return None


def _decision(
    action: FactoryBridgeAction,
    mission_status: MissionStatus,
    reason: str,
    continuation: ContinuationDecision,
    factory: FactoryDecision | None = None,
    *,
    integration_authorized: bool = False,
) -> FactoryBridgeDecision:
    return FactoryBridgeDecision(
        action=action,
        mission_status=mission_status,
        reason=reason,
        continuation=continuation,
        factory=factory,
        integration_authorized=integration_authorized,
    )
