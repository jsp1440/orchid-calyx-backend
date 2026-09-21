"""Tests for the exact-release Hassler lifecycle status surface.

The frontend renders this payload as governance fact, so the rules that matter
most are the ones about what the backend must refuse to claim: never report a
release absent when the evidence could not be read, never show an unobserved
count as a confident zero, and never let this surface imply promotion.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.taxonomy_releases import create_taxonomy_release_router
from runtime.hassler_release_lifecycle import (
    EXPECTED_FILENAME,
    EXPECTED_VERSION_LABEL,
    LIFECYCLE_STATES,
    RELINK_SURFACES,
    ReleaseObservation,
    build_downstream_relink_impact,
    build_hassler_release_status,
    classify_lifecycle,
    find_expected_release,
    matches_expected_release,
    observe_release_state,
)


def release(
    *,
    filename: str = EXPECTED_FILENAME,
    version_label: str = EXPECTED_VERSION_LABEL,
    state: str = "inspected",
    release_id: str = "sha-expected",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "release_id": release_id,
        "state": state,
        "snapshot": {"filename": filename, "version_label": version_label},
        "inspection": {"rows": 100},
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Matching the one exact release
# ---------------------------------------------------------------------------


def test_matches_the_acceptance_target_by_filename():
    assert matches_expected_release(release()) is True


def test_matches_by_version_label_when_the_filename_was_tidied():
    """A renamed file is still the same release; ABSENT would be wrong."""
    assert matches_expected_release(
        release(filename="worldorchids-26-08.csv")
    ) is True


def test_matching_ignores_case_and_surrounding_whitespace():
    assert matches_expected_release(
        release(filename=f"  {EXPECTED_FILENAME.upper()}  ")
    ) is True


def test_a_different_release_does_not_match():
    assert (
        matches_expected_release(
            release(filename="WorldOrchids 25-01.csv", version_label="WorldOrchids 25-01")
        )
        is False
    )


def test_find_expected_release_picks_it_out_of_a_mixed_inventory():
    inventory = [
        release(filename="WorldOrchids 25-01.csv", version_label="WorldOrchids 25-01"),
        release(release_id="sha-target"),
    ]
    found = find_expected_release(inventory)
    assert found is not None
    assert found["release_id"] == "sha-target"


# ---------------------------------------------------------------------------
# UNAVAILABLE is not ABSENT
# ---------------------------------------------------------------------------


def test_unreadable_inventory_reports_unavailable_never_absent():
    """The central rule: not knowing is not the same as knowing it is missing."""
    lifecycle = classify_lifecycle(
        ReleaseObservation(releases=None, inventory_error="OperationalError")
    )
    assert lifecycle["lifecycle_state"] == "UNAVAILABLE"
    assert lifecycle["lifecycle_state"] != "ABSENT"
    assert lifecycle["evidence_complete"] is False
    assert any("release_inventory" in item for item in lifecycle["unavailable_evidence"])
    assert "not the same as the release being absent" in lifecycle["lifecycle_rationale"]


def test_readable_but_empty_inventory_reports_absent():
    """Having looked and found nothing is a real finding, and complete evidence."""
    lifecycle = classify_lifecycle(ReleaseObservation(releases=()))
    assert lifecycle["lifecycle_state"] == "ABSENT"
    assert lifecycle["evidence_complete"] is True
    assert lifecycle["unavailable_evidence"] == []


def test_inventory_without_the_target_reports_absent_and_says_what_it_saw():
    lifecycle = classify_lifecycle(
        ReleaseObservation(
            releases=(
                release(filename="WorldOrchids 25-01.csv", version_label="WorldOrchids 25-01"),
            )
        )
    )
    assert lifecycle["lifecycle_state"] == "ABSENT"
    assert "1 release(s) present" in lifecycle["lifecycle_rationale"]


# ---------------------------------------------------------------------------
# Ladder classification
# ---------------------------------------------------------------------------


def test_uploaded_and_inspected_release():
    lifecycle = classify_lifecycle(ReleaseObservation(releases=(release(),)))
    assert lifecycle["lifecycle_state"] == "UPLOADED_INSPECTED"
    assert lifecycle["active_vs_staged"]["state"] == "inspected_only"


def test_smoke_verified_outranks_inspected():
    lifecycle = classify_lifecycle(
        ReleaseObservation(releases=(release(smoke_verified=True),))
    )
    assert lifecycle["lifecycle_state"] == "SMOKE_VERIFIED"


def test_partial_staging_reports_in_progress():
    lifecycle = classify_lifecycle(
        ReleaseObservation(
            releases=(release(),),
            staging={"counts": {"staged": 400, "total": 1000}},
        )
    )
    assert lifecycle["lifecycle_state"] == "STAGING_IN_PROGRESS"
    assert lifecycle["active_vs_staged"]["staged_release_id"] == "sha-expected"


def test_fully_staged_reports_staged_complete():
    lifecycle = classify_lifecycle(
        ReleaseObservation(
            releases=(release(),),
            staging={"counts": {"staged": 1000, "total": 1000}},
        )
    )
    assert lifecycle["lifecycle_state"] == "STAGED_COMPLETE"


def test_explicit_complete_flag_reports_staged_complete():
    lifecycle = classify_lifecycle(
        ReleaseObservation(releases=(release(),), staging={"complete": True})
    )
    assert lifecycle["lifecycle_state"] == "STAGED_COMPLETE"


def test_active_pointer_naming_this_release_reports_activated():
    lifecycle = classify_lifecycle(
        ReleaseObservation(releases=(release(),), active_release_id="sha-expected")
    )
    assert lifecycle["lifecycle_state"] == "ACTIVATED"
    assert lifecycle["active_vs_staged"]["state"] == "active"
    assert lifecycle["superseded"] is False


def test_active_pointer_naming_another_release_reports_superseded():
    lifecycle = classify_lifecycle(
        ReleaseObservation(releases=(release(),), active_release_id="sha-newer")
    )
    assert lifecycle["lifecycle_state"] == "SUPERSEDED"
    assert lifecycle["superseded"] is True
    assert lifecycle["superseded_by"] == "sha-newer"


def test_activation_outranks_staging():
    """An activated release is activated even while staging evidence lingers."""
    lifecycle = classify_lifecycle(
        ReleaseObservation(
            releases=(release(),),
            staging={"counts": {"staged": 10, "total": 1000}},
            active_release_id="sha-expected",
        )
    )
    assert lifecycle["lifecycle_state"] == "ACTIVATED"


def test_present_but_unrecognized_state_is_unavailable_not_inspected():
    """Do not assert an inspection that was never observed."""
    lifecycle = classify_lifecycle(
        ReleaseObservation(
            releases=({"release_id": "x", "state": "???", "snapshot": {"filename": EXPECTED_FILENAME}},)
        )
    )
    assert lifecycle["lifecycle_state"] == "UNAVAILABLE"
    assert lifecycle["evidence_complete"] is False
    assert any("release_state" in item for item in lifecycle["unavailable_evidence"])


def test_unreadable_staging_keeps_the_established_state_and_flags_the_gap():
    """Do not silently promote or demote; report what is known and what is not."""
    lifecycle = classify_lifecycle(
        ReleaseObservation(releases=(release(),), staging_error="OperationalError")
    )
    assert lifecycle["lifecycle_state"] == "UPLOADED_INSPECTED"
    assert lifecycle["evidence_complete"] is False
    assert any("staging_projection" in i for i in lifecycle["unavailable_evidence"])


def test_every_reported_state_is_on_the_declared_ladder():
    observations = [
        ReleaseObservation(releases=None, inventory_error="x"),
        ReleaseObservation(releases=()),
        ReleaseObservation(releases=(release(),)),
        ReleaseObservation(releases=(release(smoke_verified=True),)),
        ReleaseObservation(releases=(release(),), staging={"complete": True}),
        ReleaseObservation(releases=(release(),), active_release_id="sha-expected"),
        ReleaseObservation(releases=(release(),), active_release_id="other"),
    ]
    for obs in observations:
        assert classify_lifecycle(obs)["lifecycle_state"] in LIFECYCLE_STATES


# ---------------------------------------------------------------------------
# Counts are withheld, never invented
# ---------------------------------------------------------------------------


def test_unobserved_relink_counts_are_withheld_not_zero():
    """A confident 0 would read as "no downstream work". It is not the same."""
    impact = build_downstream_relink_impact(ReleaseObservation(releases=()))
    assert impact["counts_complete"] is False
    assert {d["surface"] for d in impact["domains"]} == set(RELINK_SURFACES)
    for domain in impact["domains"]:
        assert domain["count"] is None
        assert domain["count_evidence"] != "observed"
    assert impact["unresolved_blockers"]


def test_observed_relink_counts_are_reported_as_observed():
    counts = dict.fromkeys(RELINK_SURFACES, 7)
    impact = build_downstream_relink_impact(
        ReleaseObservation(releases=(), relink_counts=counts)
    )
    assert impact["counts_complete"] is True
    for domain in impact["domains"]:
        assert domain["count"] == 7
        assert domain["count_evidence"] == "observed"
    assert impact["unresolved_blockers"] == []


def test_an_observed_zero_is_preserved():
    """Zero that was actually counted is real evidence and must survive."""
    counts = dict.fromkeys(RELINK_SURFACES, 0)
    impact = build_downstream_relink_impact(
        ReleaseObservation(releases=(), relink_counts=counts)
    )
    assert all(d["count"] == 0 and d["count_evidence"] == "observed" for d in impact["domains"])
    assert impact["counts_complete"] is True


def test_partially_observed_counts_are_not_complete():
    impact = build_downstream_relink_impact(
        ReleaseObservation(releases=(), relink_counts={RELINK_SURFACES[0]: 3})
    )
    assert impact["counts_complete"] is False
    observed = [d for d in impact["domains"] if d["count_evidence"] == "observed"]
    assert len(observed) == 1


# ---------------------------------------------------------------------------
# Evidence gathering degrades instead of raising
# ---------------------------------------------------------------------------


def test_observation_survives_a_source_that_raises():
    def boom() -> Any:
        raise RuntimeError("database is down")

    observation = observe_release_state(list_releases=boom)
    assert observation.releases is None
    assert observation.inventory_error == "RuntimeError"
    # And it classifies rather than crashing the panel.
    assert classify_lifecycle(observation)["lifecycle_state"] == "UNAVAILABLE"


def test_observation_accepts_either_a_list_or_a_wrapped_payload():
    listed = observe_release_state(list_releases=lambda: [release()])
    wrapped = observe_release_state(list_releases=lambda: {"releases": [release()]})
    assert listed.releases == wrapped.releases
    assert len(listed.releases or ()) == 1


def test_staging_is_only_probed_for_the_expected_release():
    seen: list[str] = []

    def read_staging(release_id: str) -> Any:
        seen.append(release_id)
        return {"complete": True}

    observe_release_state(
        list_releases=lambda: [
            release(filename="other.csv", version_label="other", release_id="sha-other"),
            release(release_id="sha-target"),
        ],
        read_staging=read_staging,
    )
    assert seen == ["sha-target"]


def test_a_failing_staging_probe_does_not_lose_the_inventory():
    def read_staging(release_id: str) -> Any:
        raise RuntimeError("staging offline")

    observation = observe_release_state(
        list_releases=lambda: [release()], read_staging=read_staging
    )
    assert observation.releases is not None
    assert observation.staging_error == "RuntimeError"


# ---------------------------------------------------------------------------
# Governance invariants in the composed payload
# ---------------------------------------------------------------------------


def test_payload_always_states_read_only_and_no_automatic_promotion():
    for obs in (
        ReleaseObservation(releases=None, inventory_error="x"),
        ReleaseObservation(releases=(release(),), active_release_id="sha-expected"),
    ):
        payload = build_hassler_release_status(obs)
        assert payload["read_only"] is True
        assert payload["automatic_promotion"] is False


def test_payload_echoes_the_ladder_and_the_expected_target():
    payload = build_hassler_release_status(ReleaseObservation(releases=()))
    lifecycle = payload["lifecycle"]
    assert lifecycle["lifecycle_states"] == list(LIFECYCLE_STATES)
    assert lifecycle["expected_release"]["filename"] == EXPECTED_FILENAME
    assert lifecycle["expected_release"]["version_label"] == EXPECTED_VERSION_LABEL


# ---------------------------------------------------------------------------
# Route behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path) -> TestClient:
    from runtime.world_plants_release_store import WorldPlantsReleaseStore

    app = FastAPI()
    app.include_router(
        create_taxonomy_release_router(
            get_store=lambda: WorldPlantsReleaseStore(tmp_path),
            require_owner=lambda: {"owner": "test"},
            get_durable_store=lambda: None,
            get_migration_preflight=lambda: {"schema_complete": True},
        )
    )
    return TestClient(app)


def test_endpoint_answers_200_with_no_releases_present(client: TestClient):
    """An empty but readable intake is ABSENT, and still a 200 with a body."""
    response = client.get("/api/mission-control/taxonomy/hassler-release-status")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["automatic_promotion"] is False
    assert body["lifecycle"]["lifecycle_state"] == "ABSENT"


def test_endpoint_reports_a_stored_release_as_uploaded_inspected(
    client: TestClient, tmp_path
):
    from runtime.world_plants_release_store import WorldPlantsReleaseStore

    store = WorldPlantsReleaseStore(tmp_path)
    csv = b"genus,species\nCattleya,labiata\n"
    store.inspect_and_store(
        csv,
        filename=EXPECTED_FILENAME,
        version_label=EXPECTED_VERSION_LABEL,
        acquired_at="2026-08-02T00:00:00Z",
    )
    body = client.get("/api/mission-control/taxonomy/hassler-release-status").json()
    assert body["lifecycle"]["lifecycle_state"] == "UPLOADED_INSPECTED"


def test_endpoint_does_not_500_when_the_store_is_broken(tmp_path):
    """An unreachable evidence source must report, not crash the panel."""

    class BrokenStore:
        def list_reports(self):
            raise RuntimeError("intake volume unavailable")

    app = FastAPI()
    app.include_router(
        create_taxonomy_release_router(
            get_store=lambda: BrokenStore(),
            require_owner=lambda: {"owner": "test"},
            get_durable_store=lambda: None,
            get_migration_preflight=lambda: {"schema_complete": True},
        )
    )
    response = TestClient(app).get(
        "/api/mission-control/taxonomy/hassler-release-status"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle"]["lifecycle_state"] == "UNAVAILABLE"
    assert body["lifecycle"]["evidence_complete"] is False


def test_endpoint_payload_satisfies_the_frontend_consumer_contract(client: TestClient):
    """Shape check against what src/lib/hasslerReleaseLifecycle.ts reads."""
    body = client.get("/api/mission-control/taxonomy/hassler-release-status").json()

    assert isinstance(body.get("lifecycle"), dict)
    lifecycle = body["lifecycle"]
    # interpretHasslerReleaseStatus rejects anything missing these.
    assert lifecycle["lifecycle_state"] in LIFECYCLE_STATES
    assert isinstance(lifecycle["lifecycle_states"], list)
    assert isinstance(lifecycle["expected_release"], dict)
    assert isinstance(lifecycle["active_vs_staged"], dict)
    assert isinstance(lifecycle["unavailable_evidence"], list)
    assert isinstance(lifecycle["evidence_complete"], bool)
    assert isinstance(lifecycle["superseded"], bool)

    downstream = body["downstream_relink_impact"]
    assert isinstance(downstream["domains"], list)
    assert isinstance(downstream["counts_complete"], bool)
    assert isinstance(downstream["unresolved_blockers"], list)
    for domain in downstream["domains"]:
        assert isinstance(domain["surface"], str) and domain["surface"]
        assert domain["count"] is None or isinstance(domain["count"], int)
