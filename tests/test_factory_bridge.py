from __future__ import annotations

from app.calyx_orchestrator.event_continuation import (
    ContinuationPolicy,
    normalize_completion_event,
)
from app.calyx_orchestrator.factory_bridge import (
    FactoryBridgeAction,
    route_completion_to_factory,
)
from app.calyx_orchestrator.factory_policy import (
    CheckerVerdict,
    MissionStatus,
    ValidationEvidence,
    WorkIntent,
)


def _event(**overrides: object):
    payload: dict[str, object] = {
        "repository": "jsp1440/orchid-calyx-backend",
        "kind": "workflow_run",
        "event_id": "workflow_run:5001:completed",
        "head_sha": "abc123",
        "branch": "oc-maker",
        "workflow_run_id": "5001",
        "pull_request_number": 1297,
        "issue_number": 1023,
        "mission_id": "OC-1023",
        "conclusion": "success",
    }
    payload.update(overrides)
    return normalize_completion_event(payload)


def _intent(**overrides: object) -> WorkIntent:
    values: dict[str, object] = {
        "repository": "jsp1440/orchid-calyx-backend",
        "issue_number": 1023,
        "head_sha": "abc123",
        "target_branch": "oc-autonomous-integration",
    }
    values.update(overrides)
    return WorkIntent(**values)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> ValidationEvidence:
    values: dict[str, object] = {
        "maker_id": "maker-a",
        "checker_id": "checker-b",
        "checker_verdict": CheckerVerdict.PASS,
        "exact_head_verified": True,
        "required_checks_passed": True,
    }
    values.update(overrides)
    return ValidationEvidence(**values)  # type: ignore[arg-type]


def test_successful_exact_head_routes_to_safe_auto_integration() -> None:
    decision = route_completion_to_factory(
        _event(),
        current_head_sha="abc123",
        intent=_intent(),
        evidence=_evidence(),
    )

    assert decision.action is FactoryBridgeAction.AUTO_INTEGRATE
    assert decision.mission_status is MissionStatus.VALIDATING
    assert decision.integration_authorized is True
    assert decision.factory is not None
    assert decision.factory.integration_authorized is True


def test_missing_independent_checker_stays_in_validation() -> None:
    decision = route_completion_to_factory(
        _event(),
        current_head_sha="abc123",
        intent=_intent(),
        evidence=_evidence(checker_id="maker-a"),
    )

    assert decision.action is FactoryBridgeAction.REQUIRE_CHECKER
    assert decision.mission_status is MissionStatus.VALIDATING
    assert decision.integration_authorized is False


def test_stale_queue_bridge_head_reconciles_before_factory_gate() -> None:
    decision = route_completion_to_factory(
        _event(head_sha="old-head"),
        current_head_sha="abc123",
        intent=_intent(),
        evidence=_evidence(),
    )

    assert decision.action is FactoryBridgeAction.RECONCILE
    assert decision.reason == "EVENT_HEAD_DOES_NOT_MATCH_CURRENT_HEAD"
    assert decision.factory is None


def test_terminal_failure_routes_to_repair_before_checker_gate() -> None:
    decision = route_completion_to_factory(
        _event(conclusion="failure"),
        current_head_sha="abc123",
        intent=_intent(),
        evidence=_evidence(),
    )

    assert decision.action is FactoryBridgeAction.PREPARE_REPAIR
    assert decision.mission_status is MissionStatus.RUNNING
    assert decision.factory is None


def test_provider_required_continuation_parks_in_no_api_mode() -> None:
    decision = route_completion_to_factory(
        _event(),
        current_head_sha="abc123",
        intent=_intent(),
        evidence=_evidence(),
        continuation_policy=ContinuationPolicy(
            no_api_mode=True,
            provider_required=True,
        ),
    )

    assert decision.action is FactoryBridgeAction.PARK_PROVIDER_REQUIRED
    assert decision.mission_status is MissionStatus.BLOCKED
    assert decision.factory is None


def test_owner_boundary_from_factory_gate_blocks_main_target() -> None:
    decision = route_completion_to_factory(
        _event(),
        current_head_sha="abc123",
        intent=_intent(target_branch="main"),
        evidence=_evidence(),
    )

    assert decision.action is FactoryBridgeAction.OWNER_GATE
    assert decision.mission_status is MissionStatus.BLOCKED
    assert decision.integration_authorized is False


def test_factory_identity_mismatch_reconciles_instead_of_integrating() -> None:
    decision = route_completion_to_factory(
        _event(),
        current_head_sha="abc123",
        intent=_intent(repository="jsp1440/orchid-continuum-frontend"),
        evidence=_evidence(),
    )

    assert decision.action is FactoryBridgeAction.RECONCILE
    assert decision.reason == "FACTORY_REPOSITORY_IDENTITY_MISMATCH"
    assert decision.integration_authorized is False


def test_replayed_event_is_no_op_and_does_not_reenter_checker() -> None:
    event = _event()
    first = route_completion_to_factory(
        event,
        current_head_sha="abc123",
        intent=_intent(),
        evidence=_evidence(),
    )
    replay = route_completion_to_factory(
        event,
        current_head_sha="abc123",
        intent=_intent(),
        evidence=_evidence(),
        seen_fingerprints=frozenset({first.continuation.fingerprint}),
    )

    assert replay.action is FactoryBridgeAction.NO_OP
    assert replay.mission_status is MissionStatus.DONE
    assert replay.factory is None
    assert replay.integration_authorized is False
