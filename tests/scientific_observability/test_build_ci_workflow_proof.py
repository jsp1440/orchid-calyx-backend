from __future__ import annotations

import pytest

from app.scientific_observability.proof_build_ci_workflow import (
    build_fixture_events,
    run_proof,
)


def test_build_ci_workflow_proves_complete_canonical_path() -> None:
    report = run_proof()

    assert report["contract_version"] == "workflow-intelligence-e2e-proof-v1"
    assert report["FIXTURE"] is True
    assert report["environment"] == "development"
    assert report["events"] == {
        "unique": 6,
        "expected": 6,
        "first_created": True,
        "replay_noop": True,
    }
    assert all(report["proof"].values())
    assert report["reconstruction"]["current_state"] == "completed"
    assert report["reconstruction"]["retry_count"] == 1
    assert report["reconstruction"]["rework_count"] >= 1
    assert report["ranking"]["advisory_only"] is True
    assert report["ranking"]["dispatch_authority"] is False
    assert report["context"]["next_legal_actions"] == []
    assert report["runbook"]["contract_version"] == "reviewable-runbook-v1"
    assert report["mission_control"]["workflow_count"] == 1


def test_build_ci_workflow_rejects_cross_environment_contamination() -> None:
    events = build_fixture_events()
    contaminated = list(events)
    object.__setattr__(
        contaminated[-1],
        "extensions",
        {**contaminated[-1].extensions, "environment": "production"},
    )

    with pytest.raises(ValueError, match="cross-environment"):
        run_proof(contaminated)


def test_build_ci_workflow_rejects_unlabeled_fixture_input() -> None:
    events = build_fixture_events()
    unlabeled = list(events)
    object.__setattr__(
        unlabeled[0],
        "extensions",
        {**unlabeled[0].extensions, "fixture": False},
    )

    with pytest.raises(ValueError, match="unlabeled"):
        run_proof(unlabeled)
