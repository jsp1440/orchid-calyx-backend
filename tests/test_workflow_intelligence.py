"""Tests for the advisory workflow intelligence surface.

The Mission Control consumer is unusually strict: it discards the entire
payload if any authority declaration is missing, if any key anywhere looks
sensitive, or if any required field is the wrong shape. A mistake here is not
a degraded panel, it is a blank one with no explanation, so these tests aim at
exactly those rejection conditions.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.scientific_observability import (
    create_scientific_observability_router,
)
from runtime.workflow_intelligence import (
    AGENT_CONTEXT_VERSION,
    CAPABILITY_STATES,
    CONTRACT_VERSION,
    DISPLAY_STATES,
    FORBIDDEN_KEY_FRAGMENTS,
    MAX_WORKFLOWS,
    RANKING_FACTORS,
    RANKING_FORMULA_VERSION,
    SensitiveFieldError,
    WorkflowObservation,
    assert_publishable,
    build_workflow_intelligence,
    build_workflow_item,
    observe_workflows,
    rank_workflow,
)


def task(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_key": "issue-1:retrieve-evidence",
        "run_id": "run-1",
        "state": "ready",
        "module": "features/autonomy-cycle",
        "authority_class": "bounded_workspace_mutation",
        "consequence_risk": "low",
        "blocked_reason": None,
        "evidence": {},
        "retry_count": 0,
        "rework_count": 0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Redaction: the rule that silently blanks the panel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fragment", FORBIDDEN_KEY_FRAGMENTS)
def test_every_forbidden_key_fragment_is_rejected(fragment: str):
    with pytest.raises(SensitiveFieldError, match=fragment):
        assert_publishable({f"some_{fragment}_field": "value"})


def test_forbidden_key_is_caught_when_deeply_nested():
    payload = {"workflows": [{"agent_context": {"nested": {"api_key": "x"}}}]}
    with pytest.raises(SensitiveFieldError, match="api_key"):
        assert_publishable(payload)


@pytest.mark.parametrize("marker", ["sk-abc123", "Bearer eyJ", "BEGIN PRIVATE KEY"])
def test_secret_markers_in_values_are_rejected(marker: str):
    with pytest.raises(SensitiveFieldError):
        assert_publishable({"detail": f"failed with {marker}"})


def test_locality_fields_are_forbidden_because_locality_is_sensitive():
    """Orchid locality is conservation-sensitive, not merely private."""
    for key in ("latitude", "longitude", "exact_locality", "coordinate_precision"):
        with pytest.raises(SensitiveFieldError):
            assert_publishable({key: 1})


def test_a_secret_shaped_blocker_reason_is_scrubbed_not_leaked():
    """Upstream text can carry anything; it must not blank or leak the panel."""
    payload = build_workflow_intelligence(
        WorkflowObservation(
            tasks=(
                task(state="blocked", blocked_reason="auth failed: Bearer eyJhbGci"),
            )
        )
    )
    blob = repr(payload)
    assert "Bearer eyJhbGci" not in blob
    assert "[redacted]" in blob
    # And the payload as a whole is still publishable.
    assert_publishable(payload)


def test_built_payload_is_always_publishable():
    payload = build_workflow_intelligence(
        WorkflowObservation(
            tasks=(
                task(),
                task(task_key="issue-2:x", state="owner_gated"),
                task(
                    task_key="issue-3:x",
                    state="repair_backoff",
                    blocked_reason="LEASE_EXPIRED:max=0s",
                ),
            )
        )
    )
    assert_publishable(payload)


# ---------------------------------------------------------------------------
# Authority declarations the consumer verifies
# ---------------------------------------------------------------------------


def test_root_declares_advisory_and_denies_every_authority():
    payload = build_workflow_intelligence(WorkflowObservation(tasks=(task(),)))
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["advisory_only"] is True
    assert payload["human_review_required"] is True
    assert payload["dispatch_authority"] is False
    assert payload["mutation_authority"] is False
    assert payload["publication_authority"] is False
    assert payload["spending_authority"] is False


def test_every_ranking_and_context_denies_authority():
    payload = build_workflow_intelligence(
        WorkflowObservation(tasks=(task(), task(task_key="issue-2:x")))
    )
    for item in payload["workflows"]:
        ranking = item["ranking"]
        assert ranking["formula_version"] == RANKING_FORMULA_VERSION
        assert ranking["advisory_only"] is True
        for flag in (
            "dispatch_authority",
            "mutation_authority",
            "publication_authority",
            "spending_authority",
        ):
            assert ranking[flag] is False
        context = item["agent_context"]
        assert context["contract_version"] == AGENT_CONTEXT_VERSION
        for flag in (
            "dispatch_authority",
            "credential_authority",
            "mutation_authority",
            "publication_authority",
            "spending_authority",
        ):
            assert context[flag] is False


# ---------------------------------------------------------------------------
# State mapping and ranking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state,display",
    [
        ("ready", "ACTIVE"),
        ("leased", "ACTIVE"),
        ("running", "ACTIVE"),
        ("validating", "ACTIVE"),
        ("blocked", "BLOCKED"),
        ("repair_backoff", "RECENTLY_FAILED"),
        ("owner_gated", "AWAITING_REVIEW"),
        ("completed", "TERMINAL"),
    ],
)
def test_reservoir_states_map_onto_display_states(state: str, display: str):
    item = build_workflow_item(task(state=state))
    assert item is not None
    assert item["display_state"] == display
    assert item["display_state"] in DISPLAY_STATES
    assert item["capability_state"] in CAPABILITY_STATES


def test_a_task_without_identity_is_dropped_not_rendered_blank():
    assert build_workflow_item(task(task_key="")) is None


def test_ranking_names_unmeasurable_factors_instead_of_defaulting_them():
    ranking = rank_workflow({"state": "ready"})  # no counts, no evidence, no authority
    assert "retry_pressure" in ranking["unavailable_factors"]
    assert "rework_pressure" in ranking["unavailable_factors"]
    assert "evidence_present" in ranking["unavailable_factors"]
    assert ranking["factor_coverage"]["total"] == len(RANKING_FACTORS)
    assert ranking["factor_coverage"]["available"] < len(RANKING_FACTORS)


def test_a_workflow_with_no_measurable_factor_scores_null_not_zero():
    """A fabricated 0 would rank it as "nothing to see"; null says "unknown"."""
    ranking = rank_workflow({})
    assert ranking["score"] is None
    assert ranking["factor_coverage"]["available"] == 0


def test_full_coverage_is_reported_when_every_factor_is_measurable():
    ranking = rank_workflow(task())
    assert ranking["factor_coverage"]["available"] == len(RANKING_FACTORS)
    assert ranking["factor_coverage"]["ratio"] == 1.0
    assert ranking["unavailable_factors"] == []


def test_blocked_and_retried_work_outranks_healthy_work():
    calm = rank_workflow(task())
    troubled = rank_workflow(task(state="repair_backoff", retry_count=3))
    assert (troubled["score"] or 0) > (calm["score"] or 0)
    assert "BLOCKED_OR_PARKED" in troubled["reason_codes"]
    assert "RETRIED_3X" in troubled["reason_codes"]


def test_owner_gated_work_requires_human_approval():
    ranking = rank_workflow(task(state="owner_gated"))
    assert ranking["requires_human_approval"] is True
    assert "AWAITING_OWNER_AUTHORIZATION" in ranking["reason_codes"]


def test_completed_without_evidence_is_surfaced_as_a_finding():
    item = build_workflow_item(task(state="completed", evidence={}))
    assert item is not None
    codes = [f["reason_code"] for f in item["findings"]]
    assert "COMPLETED_WITHOUT_EVIDENCE" in codes


def test_cost_is_unavailable_rather_than_guessed():
    item = build_workflow_item(task())
    assert item is not None
    assert item["agent_context"]["risk_cost_constraints"]["cost_state"] == "UNAVAILABLE"


def test_cost_is_measured_when_a_provider_call_count_exists():
    item = build_workflow_item(task(evidence={"provider_call_count": 0}))
    assert item is not None
    assert item["agent_context"]["risk_cost_constraints"]["cost_state"] == "MEASURED"


def test_staleness_is_unavailable_rather_than_claimed_false():
    item = build_workflow_item(task())
    assert item is not None
    assert item["stale"] == {"classification": "UNAVAILABLE", "value": None}


def test_workflows_are_ordered_most_attention_first_and_deterministically():
    payload = build_workflow_intelligence(
        WorkflowObservation(
            tasks=(
                task(task_key="calm:1"),
                task(task_key="urgent:1", state="repair_backoff", retry_count=5),
                task(task_key="calm:2"),
            )
        )
    )
    assert payload["workflows"][0]["workflow_id"] == "urgent:1"
    again = build_workflow_intelligence(
        WorkflowObservation(
            tasks=(
                task(task_key="calm:2"),
                task(task_key="calm:1"),
                task(task_key="urgent:1", state="repair_backoff", retry_count=5),
            )
        )
    )
    assert [w["workflow_id"] for w in payload["workflows"]] == [
        w["workflow_id"] for w in again["workflows"]
    ]


def test_the_list_is_capped_so_the_consumer_never_discards_it():
    payload = build_workflow_intelligence(
        WorkflowObservation(tasks=tuple(task(task_key=f"t{i}:x") for i in range(120)))
    )
    assert len(payload["workflows"]) == MAX_WORKFLOWS


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


def test_an_unreadable_source_yields_an_empty_list_not_an_exception():
    def boom() -> Any:
        raise RuntimeError("reservoir offline")

    observation = observe_workflows(boom)
    assert observation.tasks == ()
    assert observation.source_error == "RuntimeError"
    payload = build_workflow_intelligence(observation)
    assert payload["workflows"] == []
    assert payload["source_available"] is False


def test_a_readable_but_empty_source_is_distinguishable_from_a_broken_one():
    payload = build_workflow_intelligence(observe_workflows(list))
    assert payload["workflows"] == []
    assert payload["source_available"] is True


def test_non_dict_rows_are_skipped_rather_than_crashing():
    observation = observe_workflows(lambda: [task(), "garbage", None, 42])
    assert len(observation.tasks) == 1


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def make_client(read_tasks) -> TestClient:
    app = FastAPI()
    app.include_router(create_scientific_observability_router(read_tasks=read_tasks))
    return TestClient(app)


def test_endpoint_returns_200_with_workflows():
    client = make_client(lambda: [task(), task(task_key="issue-2:x", state="blocked")])
    response = client.get("/api/scientific-observability/workflow-intelligence")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert len(body["workflows"]) == 2


def test_endpoint_returns_200_when_the_source_is_broken():
    def boom() -> Any:
        raise RuntimeError("database unreachable")

    response = make_client(boom).get(
        "/api/scientific-observability/workflow-intelligence"
    )
    assert response.status_code == 200
    assert response.json()["source_available"] is False


def test_endpoint_payload_satisfies_the_consumer_contract():
    """Shape check mirroring parseWorkflowIntelligence's rejection conditions."""
    client = make_client(
        lambda: [task(), task(task_key="issue-2:x", state="owner_gated")]
    )
    body = client.get("/api/scientific-observability/workflow-intelligence").json()

    assert body["contract_version"] == CONTRACT_VERSION
    assert body["advisory_only"] is True
    assert body["human_review_required"] is True
    assert isinstance(body["workflows"], list)
    assert len(body["workflows"]) <= MAX_WORKFLOWS

    identities = set()
    for item in body["workflows"]:
        assert item["workflow_id"] and item["workflow_id"] not in identities
        identities.add(item["workflow_id"])
        assert item["correlation_id"]
        assert item["display_state"] in DISPLAY_STATES
        assert item["capability_state"] in CAPABILITY_STATES
        assert isinstance(item["retry_count"], int) and item["retry_count"] >= 0
        assert isinstance(item["rework_count"], int) and item["rework_count"] >= 0
        assert isinstance(item["evidence_refs"], list)
        assert isinstance(item["blocker_refs"], list)
        assert item["runbook"] is None
        coverage = item["ranking"]["factor_coverage"]
        for key in ("available", "total", "ratio"):
            assert isinstance(coverage[key], (int, float))
        for finding in item["findings"]:
            assert isinstance(finding["reason_code"], str) and finding["reason_code"]
