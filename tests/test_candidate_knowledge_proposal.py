"""Provider-free proof of the proposal-only candidate-knowledge handoff."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scientific_synthesis.candidate_proposal import (
    PROPOSAL_CONTRACT,
    build_candidate_knowledge_proposal,
)
from app.scientific_synthesis.routes import router
from app.security import verify_owner_or_api_key

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
    },
    "resolved_evidence": [
        {
            "evidence_id": "evidence:phal-warm-temp-optimum",
            "source_id": "source:rittershausen-2011",
            "statement": "Phalaenopsis grow optimally at intermediate-warm temperatures.",
            "provenance": ["doi:10.1234/rittershausen2011", "page:142"],
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

_MANIFEST = {
    "contract_version": "oc-run-evidence-manifest-v1",
    "run_id": "run:phal-2026-09",
    "research_question": "What is the optimal temperature range for Phalaenopsis?",
    "taxon_id": "taxon:phalaenopsis",
    "taxonomy_snapshot_id": "world-plants:2.1.2026",
    "run_fingerprint": "a" * 64,
    "verification_state": "ready_for_review",
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
    "canonical_activation_requires_human_authority": True,
    "immutable": True,
}

_BINDING = {
    "domain": "cultivation",
    "source_object_type": "brain_reasoning_record",
    "source_object_id": 103,
    "revision_id": 1,
    "extraction_run_id": 1,
}


def _build(*, manifest=None, packet=None):
    return build_candidate_knowledge_proposal(
        manifest=manifest or deepcopy(_MANIFEST),
        verification_packet=packet or deepcopy(_PACKET),
        **_BINDING,
    )


def test_builds_deterministic_non_mutating_proposal():
    first = _build()
    second = _build()

    assert first == second
    assert first["contract_version"] == PROPOSAL_CONTRACT
    assert first["proposal_id"].startswith("candidate-proposal:")
    assert first["run_fingerprint"] == "a" * 64
    assert first["candidate_handoff_request"]["reasoning_id"] == (
        "candidate:phal-warm-grower"
    )
    assert first["candidate_handoff_request"]["qualifiers"] == {
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "canonical_knowledge_mutation_allowed": False,
    }
    assert first["review_required"] is True
    assert first["owner_submission_required"] is True
    assert first["candidate_persistence_performed"] is False
    assert first["automatic_approval"] is False
    assert first["automatic_scientific_publication"] is False
    assert first["canonical_knowledge_mutation"] is False
    assert first["knowledge_graph_mutation"] is False


def test_rejects_candidate_from_another_taxon():
    packet = deepcopy(_PACKET)
    packet["reasoning"]["candidate_knowledge"]["subject_id"] = "taxon:cattleya"
    with pytest.raises(ValueError, match="CANDIDATE_SUBJECT_MANIFEST_MISMATCH"):
        _build(packet=packet)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("human_review_required", False),
        ("automatic_scientific_publication_allowed", True),
        ("canonical_knowledge_mutation_allowed", True),
        ("canonical_activation_requires_human_authority", False),
        ("immutable", False),
    ],
)
def test_rejects_authority_expanding_manifest(field, value):
    manifest = deepcopy(_MANIFEST)
    manifest[field] = value
    with pytest.raises(ValueError, match="MANIFEST_GOVERNANCE_INVALID"):
        _build(manifest=manifest)


def test_rejects_incomplete_manifest():
    manifest = deepcopy(_MANIFEST)
    manifest["verification_state"] = "evidence_incomplete"
    with pytest.raises(ValueError, match="MANIFEST_NOT_READY_FOR_REVIEW"):
        _build(manifest=manifest)


def test_rejects_packet_requesting_canonical_mutation():
    packet = deepcopy(_PACKET)
    packet["canonical_knowledge_mutation_allowed"] = True
    with pytest.raises(ValueError, match="PACKET_GOVERNANCE_INVALID"):
        _build(packet=packet)


def test_owner_gated_route_prepares_but_does_not_execute():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    response = client.post(
        "/synthesis/candidate-proposal",
        json={
            "manifest": _MANIFEST,
            "verification_packet": _PACKET,
            **_BINDING,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_persistence_performed"] is False
    assert payload["knowledge_graph_mutation"] is False


def test_route_fails_closed_on_subject_mismatch():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)
    packet = deepcopy(_PACKET)
    packet["reasoning"]["candidate_knowledge"]["subject_id"] = "taxon:cattleya"

    response = client.post(
        "/synthesis/candidate-proposal",
        json={
            "manifest": _MANIFEST,
            "verification_packet": packet,
            **_BINDING,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "CANDIDATE_SUBJECT_MANIFEST_MISMATCH"
