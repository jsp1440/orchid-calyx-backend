"""HTTP route tests for POST /synthesis/run-manifest.

Proves that the new endpoint correctly wraps build_run_evidence_manifest()
and returns an oc-run-evidence-manifest-v1 response.  All tests are
deterministic — no model inference, no provider API calls.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scientific_synthesis.routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

# ── Phalaenopsis fixture — mirrors Brain PR #137 acceptance scenario ────────

_PACKET = {
    "contract_version": "oc-verification-handoff-v1",
    "verification_state": "ready_for_review",
    "reasoning": {
        "contract_version": "oc-parallel-v1",
        "candidate_knowledge": {
            "candidate_id": "candidate:phal-warm-grower",
            "subject_id": "taxon:phalaenopsis",
            "predicate": "grows_optimally_at",
            "object_id": "temperature:intermediate_warm",
            "evidence_ids": ["evidence:phal-warm-temp-optimum"],
            "confidence": 0.78,
            "review_state": "candidate",
            "publication_authority": False,
        },
        "contradictions": ["candidate:phal-cool-highland"],
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "private_chain_of_thought_stored": False,
    },
    "resolved_evidence": [
        {
            "evidence_id": "evidence:phal-warm-temp-optimum",
            "source_id": "source:rittershausen-2011",
            "statement": "Phalaenopsis grow optimally at intermediate-warm temperatures.",
            "provenance": ["doi:10.1234/rittershausen2011"],
            "confidence": 0.82,
        }
    ],
    "missing_evidence": [],
    "contradictions": ["candidate:phal-cool-highland"],
    "knowledge_gaps": [],
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
}

_BASE_PAYLOAD = {
    "run_id": "run:phal-2026-09",
    "research_question": "What is the optimal temperature range for Phalaenopsis cultivation?",
    "taxon_id": "taxon:phalaenopsis",
    "taxonomy_snapshot_id": "hassler:2026-09",
    "verification_packets": [_PACKET],
    "review_records": [],
    "epistemic_memory_entries": [],
}


# ── Success cases ──────────────────────────────────────────────────────────────


def test_route_returns_200():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    assert resp.status_code == 200


def test_route_returns_manifest_version():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    assert resp.json()["contract_version"] == "oc-run-evidence-manifest-v1"


def test_route_returns_run_fingerprint():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    data = resp.json()
    assert "run_fingerprint" in data
    assert len(data["run_fingerprint"]) == 64  # sha256 hex


def test_route_returns_correct_run_id():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    assert resp.json()["run_id"] == "run:phal-2026-09"


def test_route_returns_resolved_evidence_count():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    assert resp.json()["resolved_evidence_count"] == 1


def test_route_returns_governance_flags():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    data = resp.json()
    assert data["human_review_required"] is True
    assert data["automatic_scientific_publication_allowed"] is False
    assert data["canonical_knowledge_mutation_allowed"] is False
    assert data["canonical_activation_requires_human_authority"] is True
    assert data["immutable"] is True


def test_route_returns_verification_state():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    assert resp.json()["verification_state"] == "ready_for_review"


def test_route_returns_contradictions():
    resp = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    assert "candidate:phal-cool-highland" in resp.json()["contradictions"]


def test_route_fingerprint_is_deterministic():
    r1 = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    r2 = client.post("/synthesis/run-manifest", json=_BASE_PAYLOAD)
    assert r1.json()["run_fingerprint"] == r2.json()["run_fingerprint"]


# ── Validation / error cases ──────────────────────────────────────────────────


def test_route_rejects_missing_run_id():
    bad = {**_BASE_PAYLOAD, "run_id": ""}
    resp = client.post("/synthesis/run-manifest", json=bad)
    assert resp.status_code == 422


def test_route_rejects_empty_packets():
    bad = {**_BASE_PAYLOAD, "verification_packets": []}
    resp = client.post("/synthesis/run-manifest", json=bad)
    assert resp.status_code == 422


def test_route_rejects_wrong_packet_version():
    bad_packet = {**_PACKET, "contract_version": "wrong-v1"}
    bad = {**_BASE_PAYLOAD, "verification_packets": [bad_packet]}
    resp = client.post("/synthesis/run-manifest", json=bad)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "UNSUPPORTED_VERIFICATION_PACKET"


def test_route_rejects_packet_allowing_publication():
    bad_packet = {**_PACKET, "automatic_scientific_publication_allowed": True}
    bad = {**_BASE_PAYLOAD, "verification_packets": [bad_packet]}
    resp = client.post("/synthesis/run-manifest", json=bad)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PACKET_GOVERNANCE_INVALID"
