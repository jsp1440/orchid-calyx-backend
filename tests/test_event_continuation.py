from __future__ import annotations

import pytest

from app.calyx_orchestrator.event_continuation import (
    CompletionEventKind,
    ContinuationAction,
    ContinuationPolicy,
    EventNormalizationError,
    normalize_completion_event,
    reconcile_completion_event,
)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "repository": "jsp1440/orchid-calyx-backend",
        "kind": "workflow_run",
        "event_id": "workflow_run:44001:completed",
        "head_sha": "abc123",
        "branch": "oc-example",
        "workflow_run_id": "44001",
        "pull_request_number": 42,
        "program_job_id": "job-42",
        "mission_id": "mission-42",
        "conclusion": "success",
    }
    payload.update(overrides)
    return payload


def test_normalizes_exact_repository_native_identity() -> None:
    event = normalize_completion_event(_payload())

    assert event.kind is CompletionEventKind.WORKFLOW_RUN
    assert event.repository == "jsp1440/orchid-calyx-backend"
    assert event.head_sha == "abc123"
    assert event.workflow_run_id == "44001"
    assert event.pull_request_number == 42
    assert event.program_job_id == "job-42"
    assert event.mission_id == "mission-42"
    assert len(event.material_fingerprint) == 64


def test_replayed_unchanged_event_is_no_op_with_same_fingerprint() -> None:
    event = normalize_completion_event(_payload())
    first = reconcile_completion_event(event, current_head_sha="abc123")
    replay = reconcile_completion_event(
        event,
        current_head_sha="abc123",
        seen_fingerprints=frozenset({first.fingerprint}),
    )

    assert first.action is ContinuationAction.CONTINUE_PROVIDER_FREE
    assert replay.action is ContinuationAction.NO_OP_REPLAY
    assert replay.fingerprint == first.fingerprint
    assert replay.side_effects_authorized is False


def test_stale_head_fails_closed_before_continuation() -> None:
    event = normalize_completion_event(_payload())

    decision = reconcile_completion_event(event, current_head_sha="new-head")

    assert decision.action is ContinuationAction.RECONCILE_STALE_HEAD
    assert decision.side_effects_authorized is False


def test_success_can_only_admit_provider_free_reconciliation() -> None:
    event = normalize_completion_event(_payload(conclusion="success"))

    decision = reconcile_completion_event(event, current_head_sha="abc123")

    assert decision.action is ContinuationAction.CONTINUE_PROVIDER_FREE
    assert decision.side_effects_authorized is False


@pytest.mark.parametrize("conclusion", ["neutral", "skipped"])
def test_non_success_terminal_state_cannot_advance_continuation(conclusion: str) -> None:
    event = normalize_completion_event(_payload(conclusion=conclusion))

    decision = reconcile_completion_event(event, current_head_sha="abc123")

    assert decision.action is ContinuationAction.OWNER_GATE
    assert decision.reason == f"NON_SUCCESS_TERMINAL:{conclusion}"
    assert decision.side_effects_authorized is False


@pytest.mark.parametrize(
    "conclusion", ["cancelled", "timed_out", "action_required", "stale"]
)
def test_infrastructure_conclusion_parks_without_preparing_repair(
    conclusion: str,
) -> None:
    event = normalize_completion_event(_payload(conclusion=conclusion))

    decision = reconcile_completion_event(event, current_head_sha="abc123")

    assert decision.action is ContinuationAction.PARK_INFRASTRUCTURE
    assert decision.reason == f"CI_INFRASTRUCTURE_BLOCKED:{conclusion}"
    assert decision.side_effects_authorized is False


def test_failure_prepares_one_bounded_repair_lineage_without_dispatch() -> None:
    event = normalize_completion_event(_payload(conclusion="failure"))

    decision = reconcile_completion_event(event, current_head_sha="abc123")

    assert decision.action is ContinuationAction.PREPARE_REPAIR
    assert decision.reason == "TERMINAL_FAILURE:failure"
    assert decision.side_effects_authorized is False


def test_failure_halts_at_configured_repair_attempt_ceiling() -> None:
    event = normalize_completion_event(_payload(conclusion="failure"))
    policy = ContinuationPolicy(repair_attempt_count=3, max_repair_attempts=3)

    decision = reconcile_completion_event(
        event, current_head_sha="abc123", policy=policy
    )

    assert decision.action is ContinuationAction.OWNER_GATE
    assert decision.reason == "REPAIR_ATTEMPT_LIMIT_REACHED:3"
    assert decision.side_effects_authorized is False


def test_failure_below_repair_attempt_ceiling_can_prepare_repair() -> None:
    event = normalize_completion_event(_payload(conclusion="failure"))
    policy = ContinuationPolicy(repair_attempt_count=2, max_repair_attempts=3)

    decision = reconcile_completion_event(
        event, current_head_sha="abc123", policy=policy
    )

    assert decision.action is ContinuationAction.PREPARE_REPAIR


def test_provider_requirement_does_not_mask_infrastructure_state() -> None:
    event = normalize_completion_event(_payload(conclusion="cancelled"))

    decision = reconcile_completion_event(
        event,
        current_head_sha="abc123",
        policy=ContinuationPolicy(no_api_mode=True, provider_required=True),
    )

    assert decision.action is ContinuationAction.PARK_INFRASTRUCTURE


def test_provider_requirement_does_not_mask_non_terminal_state() -> None:
    event = normalize_completion_event(_payload(conclusion="in_progress"))

    decision = reconcile_completion_event(
        event,
        current_head_sha="abc123",
        policy=ContinuationPolicy(no_api_mode=True, provider_required=True),
    )

    assert decision.action is ContinuationAction.AWAIT_TERMINAL_EVENT


def test_provider_required_continuation_is_parked_in_no_api_mode() -> None:
    event = normalize_completion_event(_payload(conclusion="failure"))

    decision = reconcile_completion_event(
        event,
        current_head_sha="abc123",
        policy=ContinuationPolicy(no_api_mode=True, provider_required=True),
    )

    assert decision.action is ContinuationAction.PARK_PROVIDER_REQUIRED
    assert decision.reason == "NO_API_PROVIDER_CONTINUATION_PARKED"
    assert decision.side_effects_authorized is False


def test_owner_gate_precedes_failure_repair_or_provider_classification() -> None:
    event = normalize_completion_event(_payload(conclusion="failure"))

    decision = reconcile_completion_event(
        event,
        current_head_sha="abc123",
        policy=ContinuationPolicy(
            no_api_mode=True,
            owner_gate_required=True,
            provider_required=True,
        ),
    )

    assert decision.action is ContinuationAction.OWNER_GATE
    assert decision.reason == "OWNER_GATED_CONTINUATION"


def test_non_terminal_event_waits_without_side_effects() -> None:
    event = normalize_completion_event(_payload(conclusion="in_progress"))

    decision = reconcile_completion_event(event, current_head_sha="abc123")

    assert decision.action is ContinuationAction.AWAIT_TERMINAL_EVENT
    assert decision.side_effects_authorized is False


def test_unknown_conclusion_fails_closed_to_owner_gate() -> None:
    event = normalize_completion_event(_payload(conclusion="mystery"))

    decision = reconcile_completion_event(event, current_head_sha="abc123")

    assert decision.action is ContinuationAction.OWNER_GATE
    assert decision.reason == "UNKNOWN_EVENT_CONCLUSION:mystery"


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"repository": ""}, "REPOSITORY_REQUIRED"),
        ({"head_sha": ""}, "HEAD_SHA_REQUIRED"),
        ({"event_id": ""}, "EVENT_ID_REQUIRED"),
        ({"kind": "unsupported"}, "UNSUPPORTED_COMPLETION_EVENT_KIND"),
        ({"pull_request_number": 0}, "PULL_REQUEST_NUMBER_INVALID"),
    ],
)
@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"repair_attempt_count": -1}, "REPAIR_ATTEMPT_COUNT_INVALID"),
        ({"max_repair_attempts": 0}, "MAX_REPAIR_ATTEMPTS_INVALID"),
    ],
)
def test_invalid_repair_policy_fails_closed(
    kwargs: dict[str, int], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        ContinuationPolicy(**kwargs)


def test_invalid_or_ambiguous_identity_fails_closed(
    overrides: dict[str, object], error: str
) -> None:
    with pytest.raises(EventNormalizationError, match=error):
        normalize_completion_event(_payload(**overrides))
