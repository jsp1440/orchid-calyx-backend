"""Focused tests for the field hypothesis loop (Release-1 journey 6).

What these prove, in the order the loop runs:

- an observation snapshot always yields at least two competing hypotheses and
  the generation is deterministic and idempotent;
- the structural alternatives (ineffective visitor, misidentified subject,
  unobserved pollinator, autogamy) compete whenever they apply;
- protected locality cannot enter or leave the contract;
- supporting, contradicting and unknown evidence are recorded separately and
  never collapsed; evidence recording is idempotent;
- the lifecycle has no confirmed/accepted state, review requires an
  authenticated human, and Knowledge Graph publication is always blocked;
- every follow-up is non-destructive and the protocol constraints travel.

The store is injected explicitly so these tests behave identically with or
without ``DATABASE_URL`` in the environment.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.calyx_flywheel.locality import assert_no_sensitive_locality
from app.field_hypotheses import library, service
from app.field_hypotheses.routes import hypothesis_router, observation_router
from app.field_hypotheses.schemas import (
    KNOWLEDGE_GRAPH_PUBLICATION,
    MINIMUM_COMPETING_HYPOTHESES,
    HypothesisStatus,
    ReviewState,
)
from app.security import verify_owner_or_api_key

OBS = "obs-0001"


@pytest.fixture(autouse=True)
def memory_store():
    store = service.memory_store()
    service.configure_store(store)
    yield store
    service.configure_store(None)


@pytest.fixture()
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(observation_router)
    application.include_router(hypothesis_router)
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


SEXUAL_DECEPTION_CUES = {
    "observer_id": "auth-subject-opaque-abc123",
    "observed_at": "2026-06-15T10:30:00Z",
    "taxon_hint": "Ophrys sp.",
    "observation_text": "Single male-looking bee repeatedly landing on the lip.",
    "epistemic_certainty": "POSSIBLE",
    "locality_sensitivity": "RESEARCH_RESTRICTED",
    "interaction": {
        "visitor_observed": True,
        "visitor_group": "male_bee",
        "visitor_behaviors": ["pseudocopulation_like_contact"],
        "reward_check": "nectar_absent",
        "floral_signal_cues": ["insect_like_labellum", "scent_detected"],
    },
}

NO_VISITOR = {
    "observer_id": "auth-subject-opaque-abc123",
    "observed_at": "2026-06-15T10:30:00Z",
    "taxon_hint": "Epipactis sp.",
    "epistemic_certainty": "PROBABLE",
    "interaction": {
        "visitor_observed": False,
        "reproductive_outcome": "fruit_set_observed",
    },
}

BARE = {
    "observer_id": "auth-subject-opaque-abc123",
    "observed_at": "2026-06-15T10:30:00Z",
    "epistemic_certainty": "CONFIRMED",
}


def _generate(client: TestClient, payload: dict, observation_id: str = OBS) -> dict:
    resp = client.post(f"/api/field-observations/{observation_id}/hypotheses", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _classes(body: dict) -> list[str]:
    return [h["hypothesis_class"] for h in body["hypotheses"]]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def test_generation_yields_competing_hypotheses_and_is_idempotent(client):
    first = _generate(client, SEXUAL_DECEPTION_CUES)
    assert first["created"] is True
    assert len(first["hypotheses"]) >= MINIMUM_COMPETING_HYPOTHESES
    assert first["minimum_competing_hypotheses"] == MINIMUM_COMPETING_HYPOTHESES
    assert first["generation"]["mode"] == "deterministic_rule_library"
    assert first["generation"]["provider_called"] is False
    assert first["generation"]["library_version"] == library.LIBRARY_VERSION

    second = _generate(client, SEXUAL_DECEPTION_CUES)
    assert second["created"] is False
    assert second["set_id"] == first["set_id"]
    assert [h["hypothesis_id"] for h in second["hypotheses"]] == [
        h["hypothesis_id"] for h in first["hypotheses"]
    ]


def test_sexual_deception_cues_rank_first_and_alternatives_compete(client):
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    classes = _classes(body)
    assert classes[0] == "sexual_deception"
    top = body["hypotheses"][0]
    assert "behavior:pseudocopulation_like_contact" in top["cue_matches"]
    assert top["ko_0038_strategy"] == "sexual deception"
    # A visitor was seen, so "not an effective pollinator" must compete.
    assert "non_pollinating_visit" in classes
    # Observer certainty is POSSIBLE, so misidentification must compete.
    assert "identification_uncertainty" in classes
    # Nothing here is a fact.
    assert all(h["epistemic_status"] == "HYPOTHESIS" for h in body["hypotheses"])
    assert all(h["would_support"] and h["would_contradict"] for h in body["hypotheses"])
    assert all(h["status"] == HypothesisStatus.PROPOSED.value for h in body["hypotheses"])
    assert all(h["review_state"] == ReviewState.MACHINE_ASSISTED.value for h in body["hypotheses"])


def test_no_visitor_snapshot_proposes_unobserved_pollinator_and_autogamy(client):
    body = _generate(client, NO_VISITOR)
    classes = _classes(body)
    assert "unobserved_pollinator" in classes
    assert "autogamy" in classes
    assert "non_pollinating_visit" not in classes
    assert "visitor:absent" in body["generation"]["cue_tokens"]
    assert "outcome:fruit_set_observed" in body["generation"]["cue_tokens"]


def test_bare_confirmed_snapshot_still_gets_two_general_hypotheses(client):
    body = _generate(client, BARE)
    classes = _classes(body)
    assert len(classes) >= MINIMUM_COMPETING_HYPOTHESES
    # CONFIRMED certainty: misidentification is not forced onto the table.
    assert "identification_uncertainty" not in classes
    assert {"unobserved_pollinator", "autogamy"} <= set(classes)


def test_changed_snapshot_creates_new_set_and_updates_latest(client):
    first = _generate(client, SEXUAL_DECEPTION_CUES)
    changed = {**SEXUAL_DECEPTION_CUES, "interaction": {**SEXUAL_DECEPTION_CUES["interaction"], "reward_check": "nectar_present"}}
    second = _generate(client, changed)
    assert second["created"] is True
    assert second["set_id"] != first["set_id"]
    latest = client.get(f"/api/field-observations/{OBS}/hypotheses")
    assert latest.status_code == 200
    assert latest.json()["set_id"] == second["set_id"]


def test_latest_returns_404_before_generation(client):
    resp = client.get("/api/field-observations/never-seen/hypotheses")
    assert resp.status_code == 404


def test_library_endpoint_exposes_templates_and_question_families(client):
    resp = client.get("/api/field-hypotheses/library")
    assert resp.status_code == 200
    body = resp.json()
    assert body["library_version"] == library.LIBRARY_VERSION
    assert len(body["templates"]) == len(library.TEMPLATES)
    assert set(body["question_families"]) == set(library.QUESTION_FAMILIES)
    assert body["knowledge_graph_publication"] == KNOWLEDGE_GRAPH_PUBLICATION
    for template in body["templates"]:
        assert set(template["question_family_ids"]) <= set(library.QUESTION_FAMILIES)


# ---------------------------------------------------------------------------
# Locality protection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "leak",
    [
        {"latitude": -22.45, "longitude": -43.0},
        {"location_name": "Serra dos Órgãos"},
        {"coordinates": [1.0, 2.0]},
        {"interaction": {"visitor_observed": True, "gps": "x"}},
    ],
)
def test_snapshot_rejects_protected_locality(client, leak):
    payload = {**SEXUAL_DECEPTION_CUES, **leak}
    resp = client.post(f"/api/field-observations/{OBS}/hypotheses", json=payload)
    assert resp.status_code == 422, resp.text


def test_responses_carry_no_locality_and_do_not_echo_free_text(client):
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    assert_no_sensitive_locality(body)
    assert "observation_text" not in body["observation"]
    assert body["observation"]["locality_sensitivity"] == "RESEARCH_RESTRICTED"
    hypothesis = client.get(f"/api/field-hypotheses/{body['hypotheses'][0]['hypothesis_id']}")
    assert hypothesis.status_code == 200
    assert_no_sensitive_locality(hypothesis.json())


def test_evidence_payload_rejects_protected_locality(client):
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    hypothesis_id = body["hypotheses"][0]["hypothesis_id"]
    resp = client.post(
        f"/api/field-hypotheses/{hypothesis_id}/evidence",
        json={
            "stance": "SUPPORTING",
            "evidence_type": "directly_observed_visit",
            "summary": "seen",
            "source_kind": "field_observation",
            "recorder_subject": "auth-subject-opaque-abc123",
            "locality": "hillside above the village",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Evidence: separate stances, idempotent, never a verdict
# ---------------------------------------------------------------------------


def _evidence(stance: str, summary: str, evidence_type: str = "directly_observed_visit") -> dict:
    return {
        "stance": stance,
        "evidence_type": evidence_type,
        "summary": summary,
        "source_kind": "field_observation",
        "source_reference": OBS,
        "recorder_subject": "auth-subject-opaque-abc123",
    }


def test_evidence_is_recorded_per_stance_and_idempotently(client):
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    hypothesis_id = body["hypotheses"][0]["hypothesis_id"]
    url = f"/api/field-hypotheses/{hypothesis_id}/evidence"

    after_support = client.post(url, json=_evidence("SUPPORTING", "Male bee, copulatory posture on lip."))
    assert after_support.status_code == 200, after_support.text
    h = after_support.json()
    assert h["status"] == HypothesisStatus.UNDER_EVALUATION.value
    assert h["evidence_balance"] == {"supporting": 1, "contradicting": 0, "unknown": 0}
    assert h["evidence_state"] == "supporting_only"

    # Same item again: no duplicate.
    again = client.post(url, json=_evidence("SUPPORTING", "Male bee, copulatory posture on lip."))
    assert again.json()["evidence_balance"]["supporting"] == 1

    after_contra = client.post(url, json=_evidence("CONTRADICTING", "Nectar visible in spur.", "morphology_match"))
    h = after_contra.json()
    assert h["evidence_balance"] == {"supporting": 1, "contradicting": 1, "unknown": 0}
    assert h["evidence_state"] == "conflicting"

    after_unknown = client.post(url, json=_evidence("UNKNOWN", "Visitor sex could not be determined.", "unknown"))
    h = after_unknown.json()
    assert h["evidence_balance"] == {"supporting": 1, "contradicting": 1, "unknown": 1}
    assert h["evidence_state"] == "conflicting"
    assert [e["stance"] for e in h["evidence"]] == ["SUPPORTING", "CONTRADICTING", "UNKNOWN"]
    # Evidence never changes the epistemic status or the publication gate.
    assert h["epistemic_status"] == "HYPOTHESIS"
    assert h["review_state"] == ReviewState.MACHINE_ASSISTED.value
    assert h["knowledge_graph_publication"] == KNOWLEDGE_GRAPH_PUBLICATION


def test_evidence_on_one_hypothesis_does_not_touch_its_competitors(client):
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    first, second = body["hypotheses"][0], body["hypotheses"][1]
    client.post(f"/api/field-hypotheses/{first['hypothesis_id']}/evidence", json=_evidence("SUPPORTING", "x"))
    untouched = client.get(f"/api/field-hypotheses/{second['hypothesis_id']}").json()
    assert untouched["evidence_balance"] == {"supporting": 0, "contradicting": 0, "unknown": 0}
    assert untouched["evidence_state"] == "no_evidence"
    assert untouched["status"] == HypothesisStatus.PROPOSED.value


def test_unknown_hypothesis_returns_404(client):
    assert client.get("/api/field-hypotheses/does-not-exist").status_code == 404
    resp = client.post("/api/field-hypotheses/does-not-exist/evidence", json=_evidence("UNKNOWN", "x"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Human review gate
# ---------------------------------------------------------------------------


def test_lifecycle_vocabulary_has_no_confirmed_state():
    names = {member.value.lower() for member in HypothesisStatus}
    for forbidden in ("confirmed", "accepted", "verified", "published", "canonical"):
        assert not any(forbidden in name for name in names)


def test_review_requires_authentication(client):
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    hypothesis_id = body["hypotheses"][0]["hypothesis_id"]
    resp = client.post(
        f"/api/field-hypotheses/{hypothesis_id}/review",
        json={"status": "RETIRED", "review_state": "human_reviewed", "rationale": "Nectar present."},
    )
    assert resp.status_code == 401


def test_review_with_api_key_records_human_decision(client, monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "test-key-not-a-secret")
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    hypothesis_id = body["hypotheses"][0]["hypothesis_id"]
    resp = client.post(
        f"/api/field-hypotheses/{hypothesis_id}/review",
        headers={"X-API-Key": "test-key-not-a-secret"},
        json={
            "status": "REFINED",
            "review_state": "expert_reviewed",
            "rationale": "Restrict to the single visitor species seen.",
            "refined_statement": "Only males of the observed bee species respond to the lip as a mate.",
        },
    )
    assert resp.status_code == 200, resp.text
    h = resp.json()
    assert h["status"] == HypothesisStatus.REFINED.value
    assert h["review_state"] == ReviewState.EXPERT_REVIEWED.value
    assert h["statement"].startswith("Only males")
    assert h["human_review"]["actor"] == "backend_api_key"
    assert h["human_review"]["rationale"].startswith("Restrict")
    # Still a hypothesis, still not publishable.
    assert h["epistemic_status"] == "HYPOTHESIS"
    assert h["knowledge_graph_publication"] == KNOWLEDGE_GRAPH_PUBLICATION
    # The review is visible from the set view too.
    latest = client.get(f"/api/field-observations/{OBS}/hypotheses").json()
    reviewed = next(x for x in latest["hypotheses"] if x["hypothesis_id"] == hypothesis_id)
    assert reviewed["status"] == HypothesisStatus.REFINED.value


def test_review_with_owner_override_rejects_incomplete_decisions(app, client):
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner",
        "auth_type": "owner_session",
    }
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    hypothesis_id = body["hypotheses"][0]["hypothesis_id"]
    url = f"/api/field-hypotheses/{hypothesis_id}/review"
    # REFINED without a refined statement is not a decision.
    assert client.post(url, json={"status": "REFINED", "review_state": "human_reviewed", "rationale": "r"}).status_code == 422
    # A human cannot hand the record back to the machine state.
    assert client.post(url, json={"status": "PROPOSED", "review_state": "human_reviewed", "rationale": "r"}).status_code == 422
    assert client.post(url, json={"status": "RETIRED", "review_state": "machine_assisted", "rationale": "r"}).status_code == 422
    ok = client.post(url, json={"status": "RETIRED", "review_state": "needs_followup", "rationale": "Insufficient visits."})
    assert ok.status_code == 200
    assert ok.json()["status"] == HypothesisStatus.RETIRED.value
    assert ok.json()["human_review"]["actor"] == "owner"


# ---------------------------------------------------------------------------
# Follow-up protocol
# ---------------------------------------------------------------------------


def test_follow_up_protocol_is_non_destructive_and_discriminating(client):
    body = _generate(client, SEXUAL_DECEPTION_CUES)
    protocol = body["follow_up_protocol"]
    assert protocol
    assert all(step["non_destructive"] is True for step in protocol)
    assert all(step["discriminates"] for step in protocol)
    assert len({step["step_id"] for step in protocol}) == len(protocol)
    # On-site actions come first; later revisits follow.
    on_site_flags = [step["while_on_site"] for step in protocol]
    assert on_site_flags == sorted(on_site_flags, reverse=True)
    constraints = " ".join(body["protocol_constraints"]).lower()
    assert "do not collect" in constraints
    assert "locality" in constraints
    assert "not scientific determinations" in constraints


def test_every_template_has_non_empty_testable_content():
    for template in library.TEMPLATES:
        assert template.predictions and template.would_support and template.would_contradict
        assert template.follow_ups
        assert set(template.question_family_ids) <= set(library.QUESTION_FAMILIES)


def test_main_app_registers_field_hypothesis_routes():
    pytest.importorskip("psycopg", reason="app.main imports the full router set")
    from app.main import app as main_app

    paths = {route.path for route in main_app.routes}
    assert "/api/field-observations/{observation_id}/hypotheses" in paths
    assert "/api/field-hypotheses/{hypothesis_id}/evidence" in paths
    assert "/api/field-hypotheses/{hypothesis_id}/review" in paths
    assert "/api/field-hypotheses/library" in paths
