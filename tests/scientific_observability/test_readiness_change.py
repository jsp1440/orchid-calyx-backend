"""SCI-OBS-003 readiness-change lifecycle contract tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.scientific_observability.anomalies import AnomalyCode
from app.scientific_observability.readiness import (
    CALCULATION_VERSION,
    DimensionScore,
    DimensionState,
    build_readiness,
)
from app.scientific_observability.readiness_change import (
    ReadinessChangeError,
    ReadinessChangeKind,
    ReadinessChangeLifecycle,
    ReadinessSnapshot,
)
from app.scientific_observability.service import ObservabilityService
from app.scientific_observability.store import ObservationStore


def _payload(
    *,
    state: str = DimensionState.AVAILABLE,
    numerator: int | None = 4,
    denominator: int | None = 4,
    missing: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
    measured_at: str = "2026-09-12T12:00:00+00:00",
) -> dict:
    return build_readiness(
        {
            "engineering_health": DimensionScore(
                key="engineering_health",
                state=state,
                numerator=numerator,
                denominator=denominator,
                missing_requirements=list(missing),
                upstream_blockers=list(blockers),
                measured_at=measured_at,
            )
        },
        coverage_inputs={"taxonomy": True, "provenance": True},
    )


def _snapshot(payload: dict, **overrides) -> ReadinessSnapshot:
    values = {
        "module_id": "mission-control",
        "project_id": "orchid-continuum",
        "environment": "test",
        "readiness": payload,
        "evidence_refs": ("ci-run-788",),
        "source_ref": "readiness-snapshot-1",
    }
    values.update(overrides)
    return ReadinessSnapshot(**values)


def _lifecycle() -> tuple[ReadinessChangeLifecycle, ObservationStore]:
    store = ObservationStore()
    return ReadinessChangeLifecycle(ObservabilityService(store)), store


def test_unchanged_snapshot_and_timestamp_only_change_emit_nothing():
    lifecycle, store = _lifecycle()
    before = _payload()
    after = _payload(measured_at="2026-09-12T12:05:00+00:00")
    after["generated_at"] = "2026-09-12T12:05:00+00:00"

    result = lifecycle.compare(_snapshot(before), _snapshot(after))

    assert result.classification is ReadinessChangeKind.UNCHANGED
    assert result.created is False
    assert result.event is None
    assert len(store) == 0


def test_verified_improvement_emits_one_non_authoritative_event():
    lifecycle, store = _lifecycle()
    before = _payload(
        state=DimensionState.CONDITIONAL,
        numerator=3,
        denominator=4,
        missing=("consumer-contract",),
    )
    after = _payload()

    result = lifecycle.compare(_snapshot(before), _snapshot(after))

    assert result.classification is ReadinessChangeKind.IMPROVED
    assert result.created is True
    assert result.event["event_type"] == "module.readiness.changed"
    assert result.event["safe_status"]["reason_code"] == "READINESS_IMPROVED"
    assert result.anomalies == ()
    assert result.to_dict()["authority"]["mutates_authoritative_state"] is False
    assert len(store) == 1


def test_regression_routes_one_stable_workbench_binding_and_replay_is_noop():
    lifecycle, store = _lifecycle()
    before = _payload()
    after = _payload(
        state=DimensionState.BLOCKED,
        numerator=3,
        denominator=4,
        missing=("exact-head-validation",),
        blockers=("ci-failed",),
    )
    old = _snapshot(before)
    new = _snapshot(after, source_ref="readiness-snapshot-2")

    first = lifecycle.compare(old, new)
    replay = lifecycle.compare(old, new)

    assert first.classification is ReadinessChangeKind.REGRESSED
    assert first.created is True
    assert [item["code"] for item in first.anomalies] == [AnomalyCode.READINESS_REGRESSION]
    assert len(first.review_bindings) == 1
    assert first.review_bindings[0]["review_type"] == (
        "SCI_OBS_ANOMALY:READINESS_REGRESSION"
    )
    assert first.review_bindings[0]["authoritative_state_mutated"] is False
    assert replay.created is False
    assert replay.event["event_id"] == first.event["event_id"]
    assert replay.anomalies == ()
    assert replay.review_bindings == ()
    assert len(store) == 1


def test_unknown_transition_is_incomparable_and_preserves_unknown_not_zero():
    lifecycle, store = _lifecycle()
    before = _payload(
        state=DimensionState.UNAVAILABLE,
        numerator=None,
        denominator=None,
    )
    after = _payload()

    result = lifecycle.compare(_snapshot(before), _snapshot(after))

    assert result.classification is ReadinessChangeKind.INCOMPARABLE
    assert result.reason_code == "READINESS_CHANGE_INCOMPARABLE"
    assert result.created is False
    assert len(store) == 0


def test_missing_evidence_and_forged_authority_fail_closed():
    lifecycle, _ = _lifecycle()
    payload = _payload()

    with pytest.raises(ReadinessChangeError, match="requires evidence"):
        lifecycle.compare(
            _snapshot(payload, evidence_refs=()),
            _snapshot(payload, evidence_refs=()),
        )

    forged = deepcopy(payload)
    forged["publication_authority"] = True
    with pytest.raises(ReadinessChangeError, match="publication authority"):
        lifecycle.compare(_snapshot(payload), _snapshot(forged))


def test_incompatible_versions_and_cross_environment_fail_closed():
    lifecycle, store = _lifecycle()
    payload = _payload()
    incompatible = deepcopy(payload)
    incompatible["contract_version"] = "sci-obs-readiness-v2"

    with pytest.raises(ReadinessChangeError, match="incompatible"):
        lifecycle.compare(_snapshot(payload), _snapshot(incompatible))
    with pytest.raises(ReadinessChangeError, match="cross-identity"):
        lifecycle.compare(
            _snapshot(payload, environment="test"),
            _snapshot(payload, environment="production"),
        )
    assert len(store) == 0


def test_sensitive_identifiers_and_unbounded_metadata_fail_closed():
    lifecycle, _ = _lifecycle()
    payload = _payload()

    with pytest.raises(ReadinessChangeError, match="protected"):
        lifecycle.compare(
            _snapshot(payload),
            _snapshot(payload, source_ref="api_key"),
        )

    oversized = deepcopy(payload)
    oversized["dimensions"]["engineering_health"]["missing_requirements"] = [
        f"requirement-{index}" for index in range(33)
    ]
    with pytest.raises(ReadinessChangeError, match="bounded"):
        lifecycle.compare(_snapshot(payload), _snapshot(oversized))


def test_mixed_improvement_and_regression_is_incomparable():
    lifecycle, store = _lifecycle()
    before = _payload(
        state=DimensionState.CONDITIONAL,
        numerator=3,
        denominator=4,
        missing=("consumer-contract",),
    )
    after = _payload(
        state=DimensionState.CONDITIONAL,
        numerator=4,
        denominator=4,
        blockers=("ci-failed",),
    )

    result = lifecycle.compare(_snapshot(before), _snapshot(after))

    assert result.classification is ReadinessChangeKind.INCOMPARABLE
    assert result.created is False
    assert len(store) == 0


def test_dimension_calculation_version_mismatch_fails_closed():
    lifecycle, _ = _lifecycle()
    payload = _payload()
    changed = deepcopy(payload)
    changed["dimensions"]["engineering_health"]["calculation_version"] = (
        CALCULATION_VERSION + "-forged"
    )

    with pytest.raises(ReadinessChangeError, match="calculation version"):
        lifecycle.compare(_snapshot(payload), _snapshot(changed))
