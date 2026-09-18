"""Journey 10 — approving a human observation offers it for review, never as fact.

The moderation path previously ended at a label: approving an observation left
three comment lines where the promotion hook was meant to be, so an approved
sighting reached nothing. These tests pin the behaviour that closes it, and the
boundaries it must not cross:

* a moderator's approval files a *candidate* for scientific review;
* the candidate says the taxon name is the submitter's wording and unresolved,
  that the report is a human observation and not a verified occurrence, and that
  it may not be promoted without review;
* the candidate does not carry the verbatim locality or the submitter's subject;
* retracting an approval withdraws the candidate instead of leaving a retracted
  sighting in a reviewer's queue.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.community_observation import service as observation_service
from app.community_observation.models import (
    CANDIDATE_SCHEMA,
    EVIDENCE_STATE_HUMAN_REPORTED,
    CandidateState,
    CommunityObservation,
    CommunityObservationCandidate,
    ModerationState,
    ObservationEpistemicLabel,
)
from app.community_observation.routes import router
from app.community_observation.service import (
    CandidateRepository,
    CommunityObservationRepository,
    build_candidate,
    reconcile_candidate,
)
from app.security import verify_owner_or_api_key

LOCALITY = "Serra do Mar, Brazil — 200 m north of the trail junction"
SUBJECT = "auth-subject-9f31"


@pytest.fixture(autouse=True)
def isolated_store():
    observation_service.configure_store(observation_service.memory_store())
    yield
    observation_service.configure_store(None)


@pytest.fixture()
def repos():
    store = observation_service.get_store()
    return CommunityObservationRepository(store), CandidateRepository(store)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner:jeff",
        "auth_type": "owner_session",
    }
    return TestClient(app)


@pytest.fixture()
def anonymous_client(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _observation(**overrides) -> CommunityObservation:
    base = {
        "submitter_auth_subject": SUBJECT,
        "taxon_name_verbatim": "Cattleya labiata",
        "location_verbatim": LOCALITY,
        "observation_date": date(2026, 6, 15),
        "epistemic_label": ObservationEpistemicLabel.PROBABLE,
        "evidence_media_ids": ["11111111-1111-1111-1111-111111111111"],
    }
    base.update(overrides)
    return CommunityObservation(**base)


def _approved(**overrides) -> CommunityObservation:
    return _observation(
        moderation_state=ModerationState.APPROVED,
        moderated_at=datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
        moderated_by="owner:jeff",
        **overrides,
    )


# --------------------------------------------------------------------------
# What approval produces
# --------------------------------------------------------------------------


def test_approval_files_a_candidate_bound_to_the_observation():
    observation = _approved()
    candidate = build_candidate(observation)

    assert candidate.observation_id == observation.id
    assert candidate.schema_name == CANDIDATE_SCHEMA
    assert candidate.candidate_state is CandidateState.PENDING_REVIEW
    assert candidate.approved_by == "owner:jeff"
    assert candidate.approved_at == observation.moderated_at


def test_the_candidate_keeps_the_submitters_wording_and_calls_it_unresolved():
    candidate = build_candidate(_approved())

    assert candidate.taxon_name_verbatim == "Cattleya labiata"
    assert candidate.taxon_resolved is False
    assert candidate.submitter_epistemic_label is ObservationEpistemicLabel.PROBABLE
    assert candidate.evidence_state == EVIDENCE_STATE_HUMAN_REPORTED


def test_the_candidate_may_not_be_promoted_by_itself():
    candidate = build_candidate(_approved())

    assert candidate.review_required is True
    assert candidate.auto_promotion_blocked is True
    assert candidate.graph_mutation is False


def test_the_candidate_leaves_the_locality_and_the_submitter_behind():
    observation = _approved()
    serialized = json.dumps(
        build_candidate(observation).model_dump(mode="json", by_alias=True)
    )

    assert LOCALITY not in serialized
    assert SUBJECT not in serialized
    assert "location_verbatim" not in serialized
    assert "submitter_auth_subject" not in serialized


def test_the_candidate_states_that_locality_and_media_still_need_review():
    candidate = build_candidate(_approved())

    assert candidate.locality_withheld is True
    assert candidate.locality_disclosure_state == "WITHHELD_PENDING_REVIEW"
    # Submitted photographs can carry embedded coordinates that approval did not
    # inspect, so the candidate must say so rather than imply the media is safe.
    assert candidate.media_locality_review_required is True


def test_the_candidate_carries_provenance_back_to_the_observation():
    observation = _approved()
    chain = build_candidate(observation).provenance_chain

    assert f"community_observation:{observation.id}" in chain
    assert any(entry.startswith("moderation_decision:APPROVED@") for entry in chain)
    assert "moderated_by:owner:jeff" in chain


# --------------------------------------------------------------------------
# What approval refuses to produce
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        ModerationState.SUBMITTED,
        ModerationState.SCREENED,
        ModerationState.QUARANTINED,
        ModerationState.REJECTED,
    ],
)
def test_only_an_approved_observation_may_become_a_candidate(state):
    with pytest.raises(ValueError, match="CANDIDATE_REQUIRES_APPROVAL"):
        build_candidate(_observation(moderation_state=state))


@pytest.mark.parametrize(
    ("field", "value", "invariant"),
    [
        ("taxon_resolved", True, "CANDIDATE_TAXON_RESOLVED_INVARIANT"),
        ("evidence_state", "VERIFIED_OCCURRENCE", "CANDIDATE_EVIDENCE_STATE_INVARIANT"),
        ("review_required", False, "CANDIDATE_REVIEW_REQUIRED_INVARIANT"),
        ("auto_promotion_blocked", False, "CANDIDATE_AUTO_PROMOTION_INVARIANT"),
        ("graph_mutation", True, "CANDIDATE_GRAPH_MUTATION_INVARIANT"),
        ("locality_withheld", False, "CANDIDATE_LOCALITY_INVARIANT"),
        ("media_locality_review_required", False, "CANDIDATE_MEDIA_LOCALITY_INVARIANT"),
        ("schema", "oc.something-else.v1", "CANDIDATE_SCHEMA_INVARIANT"),
    ],
)
def test_a_relaxed_authority_flag_raises_rather_than_producing_a_record(
    field, value, invariant
):
    fields = {
        "observation_id": uuid.uuid4(),
        "taxon_name_verbatim": "Cattleya labiata",
        "observation_date": date(2026, 6, 15),
        "submitter_epistemic_label": ObservationEpistemicLabel.PROBABLE,
        "approved_at": datetime(2026, 6, 20, tzinfo=timezone.utc),
        field: value,
    }
    with pytest.raises(ValueError, match=invariant):
        CommunityObservationCandidate(**fields)


# --------------------------------------------------------------------------
# Reconciliation: one candidate per observation, withdrawn on retraction
# --------------------------------------------------------------------------


def test_approving_the_same_observation_twice_leaves_one_candidate(repos):
    observations, candidates = repos
    observation = observations.save(_observation())

    for _ in range(2):
        moderated = observations.moderate(
            observation.id,
            new_state=ModerationState.APPROVED,
            reason="clear photograph",
            moderated_by="owner:jeff",
        )
        reconcile_candidate(moderated, candidates=candidates)

    assert len(candidates.list()) == 1


def test_retracting_an_approval_withdraws_the_candidate_instead_of_deleting_it(repos):
    observations, candidates = repos
    observation = observations.save(_observation())

    approved = observations.moderate(
        observation.id,
        new_state=ModerationState.APPROVED,
        reason="clear photograph",
        moderated_by="owner:jeff",
    )
    reconcile_candidate(approved, candidates=candidates)

    retracted = observations.moderate(
        observation.id,
        new_state=ModerationState.QUARANTINED,
        reason="second opinion says the plant is cultivated",
        moderated_by="owner:jeff",
    )
    reconcile_candidate(retracted, candidates=candidates)

    stored = candidates.get(observation.id)
    assert stored is not None, "a retraction is part of the record, not an erasure"
    assert stored.candidate_state is CandidateState.WITHDRAWN
    assert stored.withdrawn_at is not None
    assert "QUARANTINED" in (stored.withdrawn_reason or "")
    assert candidates.list(candidate_state=CandidateState.PENDING_REVIEW) == []


def test_a_never_approved_observation_files_nothing(repos):
    observations, candidates = repos
    observation = observations.save(_observation())

    rejected = observations.moderate(
        observation.id,
        new_state=ModerationState.REJECTED,
        reason="not an orchid",
        moderated_by="owner:jeff",
    )

    assert reconcile_candidate(rejected, candidates=candidates) is None
    assert candidates.list() == []


def test_re_approving_after_a_retraction_returns_it_to_the_review_queue(repos):
    observations, candidates = repos
    observation = observations.save(_observation())

    for state in (
        ModerationState.APPROVED,
        ModerationState.QUARANTINED,
        ModerationState.APPROVED,
    ):
        moderated = observations.moderate(
            observation.id, new_state=state, reason=None, moderated_by="owner:jeff"
        )
        reconcile_candidate(moderated, candidates=candidates)

    stored = candidates.get(observation.id)
    assert stored is not None
    assert stored.candidate_state is CandidateState.PENDING_REVIEW
    assert stored.withdrawn_at is None


def test_a_second_retraction_does_not_overwrite_the_first_withdrawal(repos):
    observations, candidates = repos
    observation = observations.save(_observation())

    approved = observations.moderate(
        observation.id, new_state=ModerationState.APPROVED, reason=None, moderated_by="owner:jeff"
    )
    reconcile_candidate(approved, candidates=candidates)

    first = observations.moderate(
        observation.id, new_state=ModerationState.QUARANTINED, reason=None, moderated_by="owner:jeff"
    )
    reconcile_candidate(first, candidates=candidates)
    first_withdrawal = candidates.get(observation.id)
    assert first_withdrawal is not None

    second = observations.moderate(
        observation.id, new_state=ModerationState.REJECTED, reason=None, moderated_by="owner:jeff"
    )
    reconcile_candidate(second, candidates=candidates)

    assert candidates.get(observation.id).withdrawn_at == first_withdrawal.withdrawn_at


# --------------------------------------------------------------------------
# Over HTTP
# --------------------------------------------------------------------------


def _submit(client) -> str:
    resp = client.post(
        "/api/community/observations",
        json={
            "taxon_name_verbatim": "Cattleya labiata",
            "location_verbatim": LOCALITY,
            "observation_date": "2026-06-15",
            "epistemic_label": "PROBABLE",
            "evidence_media_ids": ["11111111-1111-1111-1111-111111111111"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_moderating_to_approved_over_http_fills_the_review_queue(client):
    observation_id = _submit(client)

    assert client.get("/api/community/observation-candidates").json()["total"] == 0

    resp = client.patch(
        f"/api/community/observations/{observation_id}/moderate",
        json={"observation_id": observation_id, "new_state": "APPROVED", "reason": "ok"},
    )
    assert resp.status_code == 200, resp.text

    queue = client.get("/api/community/observation-candidates")
    assert queue.status_code == 200, queue.text
    body = queue.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["observation_id"] == observation_id
    assert item["evidence_state"] == EVIDENCE_STATE_HUMAN_REPORTED
    assert item["taxon_resolved"] is False
    assert item["auto_promotion_blocked"] is True
    assert item["review_required"] is True
    assert item["locality_withheld"] is True


def test_the_review_queue_never_returns_the_locality_or_the_submitter(client):
    observation_id = _submit(client)
    client.patch(
        f"/api/community/observations/{observation_id}/moderate",
        json={"observation_id": observation_id, "new_state": "APPROVED", "reason": "ok"},
    )

    assert LOCALITY not in client.get("/api/community/observation-candidates").text


def test_the_review_queue_is_not_public(anonymous_client):
    resp = anonymous_client.get("/api/community/observation-candidates")
    assert resp.status_code in (401, 403), resp.text


def test_the_review_queue_reflects_a_retraction_made_over_http(client):
    observation_id = _submit(client)
    for state in ("APPROVED", "REJECTED"):
        resp = client.patch(
            f"/api/community/observations/{observation_id}/moderate",
            json={"observation_id": observation_id, "new_state": state, "reason": None},
        )
        assert resp.status_code == 200, resp.text

    pending = client.get(
        "/api/community/observation-candidates", params={"candidate_state": "PENDING_REVIEW"}
    ).json()
    withdrawn = client.get(
        "/api/community/observation-candidates", params={"candidate_state": "WITHDRAWN"}
    ).json()

    assert pending["total"] == 0
    assert withdrawn["total"] == 1


def test_the_main_app_serves_the_review_queue():
    from app.main import app as main_app

    paths = {route.path for route in main_app.routes}
    assert "/api/community/observation-candidates" in paths
