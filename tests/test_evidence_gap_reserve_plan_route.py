"""GET /api/runner/knowledge-gaps/reserve-plan: read-only, JSON, fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime import planner_router
from runtime.evidence_coverage_gaps import EvidenceCoverageGapSource
from runtime.evidence_gap_reserve_plan import UNAVAILABLE_STATUS
from tests.test_evidence_coverage_gaps import sample_kg
from tests.test_evidence_gap_reserve_adapter import LABELS, frontend_admits

PATH = "/api/runner/knowledge-gaps/reserve-plan"
FIXTURE = Path(__file__).parent / "fixtures" / "evidence_gap_reserve_plan.json"
# Keys BackendReservePlan declares in orchid-continuum-frontend
# src/lib/control-plane/backendReserveQueueBridge.ts:27-35.
PLAN_KEYS = {
    "schema",
    "reserve_depth",
    "queued_count",
    "deficit",
    "status",
    "proposals",
    "rejections",
}
SAFE_STATUSES = {
    "reserve_satisfied",
    "refill_planned",
    "queue_empty_healthy",
    "reserve_below_target_no_eligible_candidates",
}


def client_with(monkeypatch, source: EvidenceCoverageGapSource | None) -> TestClient:
    if source is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setattr(planner_router, "evidence_coverage_source", lambda: source)
    app = FastAPI()
    app.include_router(planner_router.router)
    return TestClient(app)


def kg_source() -> EvidenceCoverageGapSource:
    kg = sample_kg()
    kg.labels = dict(LABELS)
    return EvidenceCoverageGapSource(lambda callback: callback(kg.cursor()))


def test_live_kg_plan_is_the_frontend_backend_reserve_plan(monkeypatch):
    resp = client_with(monkeypatch, kg_source()).get(PATH)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert PLAN_KEYS <= set(body)
    assert body["schema"] == "oc.reserve-refill.v1"
    assert body["status"] == "refill_planned" and body["status"] in SAFE_STATUSES
    assert body["status_reason"] is None
    assert body["reserve_depth"] == 3 and body["queued_count"] == 0
    assert "empty_queue_snapshot" in body["snapshot_basis"]
    assert len(body["proposals"]) == 3
    for proposal in body["proposals"]:
        assert proposal["source_kind"] == "objective"
        assert proposal["queue_source_kind"] == "brain-knowledge-gap"
        assert len(proposal["material_fingerprint"]) == 64
        assert frontend_admits(proposal["source_payload"]) is None
    # The frontend vitest uses exactly this payload.
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == body


def test_caller_fingerprints_exclude_already_held_work(monkeypatch):
    client = client_with(monkeypatch, kg_source())
    first = client.get(PATH).json()["proposals"][0]["material_fingerprint"]
    second = client.get(PATH, params={"fingerprint": [first]}).json()
    assert first not in {p["material_fingerprint"] for p in second["proposals"]}
    assert (
        client.get(PATH, params={"fingerprint": ["not-a-fingerprint"]}).status_code
        == 422
    )
    assert client.get(PATH, params={"reserve_depth": 9}).status_code == 422


@pytest.mark.parametrize(
    "source,reason",
    [
        (None, "DATABASE_URL is not configured"),
        (
            EvidenceCoverageGapSource(lambda cb: cb(None)),
            "no knowledge-graph connection",
        ),
    ],
)
def test_no_kg_is_zero_proposals_with_the_reason_never_keyword_gaps(
    monkeypatch, source, reason
):
    resp = client_with(monkeypatch, source).get(PATH)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["proposals"] == []
    assert (
        body["status"] == UNAVAILABLE_STATUS
    )  # outside the frontend's safe set: blocked
    assert body["status"] not in SAFE_STATUSES
    assert reason in body["status_reason"]
    assert body["source_gap_source"] == "stored_record_fail_closed"


def test_planner_failure_is_json_not_a_500(monkeypatch):
    from runtime import evidence_gap_reserve_plan as module

    def boom(*_args, **_kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(module, "plan_evidence_gap_refill", boom)
    resp = client_with(monkeypatch, kg_source()).get(PATH)
    assert resp.status_code == 200
    assert resp.json()["status"] == UNAVAILABLE_STATUS
    assert resp.json()["proposals"] == []


def test_route_is_get_only_like_its_sibling_reads(monkeypatch):
    client = client_with(monkeypatch, kg_source())
    assert client.post(PATH).status_code == 405
