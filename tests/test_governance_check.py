"""Tests for check_manifest_governance and POST /synthesis/governance-check.

All tests are deterministic and provider-free. No model inference, no network,
no paid API calls. Fixtures use the governance flags hardcoded in every manifest
produced by build_run_evidence_manifest (human_review_required=True,
automatic_scientific_publication_allowed=False, etc.).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.scientific_synthesis.governance import (
    GovernanceOutcome,
    check_manifest_governance,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

MANIFEST_VERSION = "oc-run-evidence-manifest-v1"

# Minimal valid manifest produced by build_run_evidence_manifest with default flags.
BASE_MANIFEST = {
    "contract_version": MANIFEST_VERSION,
    "run_id": "run:phal-2026-09",
    "research_question": "What is the optimal temperature range for Phalaenopsis?",
    "taxon_id": "taxon:phalaenopsis",
    "taxonomy_snapshot_id": "hassler:2026-09",
    "run_fingerprint": "a" * 64,
    "created_at_utc": "2026-09-12T00:00:00+00:00",
    "verification_state": "ready_for_review",
    "resolved_evidence_count": 1,
    "missing_evidence_count": 0,
    "knowledge_gap_count": 0,
    "contradictions": [],
    "review_decision": None,
    "epistemic_state": None,
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
    "canonical_activation_requires_human_authority": True,
    "immutable": True,
}


def manifest(**overrides):
    return {**BASE_MANIFEST, **overrides}


# ── Pure function tests ───────────────────────────────────────────────────────


class TestCheckManifestGovernance:
    def test_canonical_knowledge_mutation_blocked(self):
        decision = check_manifest_governance(BASE_MANIFEST, "canonical_knowledge_mutation")
        assert decision.outcome is GovernanceOutcome.BLOCKED
        assert not decision.admitted
        assert "canonical_knowledge_mutation_allowed:false" in decision.blocking_flags

    def test_automatic_scientific_publication_blocked(self):
        decision = check_manifest_governance(
            BASE_MANIFEST, "automatic_scientific_publication"
        )
        assert decision.outcome is GovernanceOutcome.BLOCKED
        assert not decision.admitted
        assert "automatic_scientific_publication_allowed:false" in decision.blocking_flags

    def test_canonical_activation_blocked(self):
        decision = check_manifest_governance(BASE_MANIFEST, "canonical_activation")
        assert decision.outcome is GovernanceOutcome.BLOCKED
        assert not decision.admitted
        assert "canonical_activation_requires_human_authority:true" in decision.blocking_flags

    def test_human_review_submission_always_admitted(self):
        decision = check_manifest_governance(BASE_MANIFEST, "human_review_submission")
        assert decision.outcome is GovernanceOutcome.ADMITTED
        assert decision.admitted
        assert decision.blocking_flags == []

    def test_read_evidence_always_admitted(self):
        decision = check_manifest_governance(BASE_MANIFEST, "read_evidence")
        assert decision.outcome is GovernanceOutcome.ADMITTED
        assert decision.admitted

    def test_build_manifest_always_admitted(self):
        decision = check_manifest_governance(BASE_MANIFEST, "build_manifest")
        assert decision.outcome is GovernanceOutcome.ADMITTED
        assert decision.admitted

    def test_build_synthesis_admitted_when_ready_for_review(self):
        decision = check_manifest_governance(BASE_MANIFEST, "build_synthesis")
        assert decision.outcome is GovernanceOutcome.ADMITTED
        assert decision.admitted

    def test_build_synthesis_blocked_when_evidence_incomplete(self):
        m = manifest(verification_state="evidence_incomplete")
        decision = check_manifest_governance(m, "build_synthesis")
        assert decision.outcome is GovernanceOutcome.BLOCKED
        assert not decision.admitted
        assert "verification_state:evidence_incomplete" in decision.blocking_flags

    def test_build_synthesis_admitted_when_validation_required(self):
        m = manifest(verification_state="validation_required")
        decision = check_manifest_governance(m, "build_synthesis")
        assert decision.outcome is GovernanceOutcome.ADMITTED
        assert decision.admitted

    def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="UNKNOWN_ACTION"):
            check_manifest_governance(BASE_MANIFEST, "destroy_everything")

    def test_wrong_contract_version_raises(self):
        m = manifest(contract_version="wrong-v1")
        with pytest.raises(ValueError, match="MANIFEST_CONTRACT_INVALID"):
            check_manifest_governance(m, "read_evidence")

    def test_missing_fingerprint_raises(self):
        m = {k: v for k, v in BASE_MANIFEST.items() if k != "run_fingerprint"}
        with pytest.raises(ValueError, match="MANIFEST_FINGERPRINT_MISSING"):
            check_manifest_governance(m, "read_evidence")

    def test_malformed_fingerprint_raises(self):
        m = manifest(run_fingerprint="not-a-sha256")
        with pytest.raises(ValueError, match="MANIFEST_FINGERPRINT_MISSING"):
            check_manifest_governance(m, "read_evidence")

    def test_fingerprint_wrong_length_raises(self):
        m = manifest(run_fingerprint="a" * 63)
        with pytest.raises(ValueError, match="MANIFEST_FINGERPRINT_MISSING"):
            check_manifest_governance(m, "read_evidence")

    def test_canonical_mutation_admitted_when_explicitly_allowed(self):
        # Hypothetical: if a manifest were ever built with the flag set to True
        m = manifest(canonical_knowledge_mutation_allowed=True)
        decision = check_manifest_governance(m, "canonical_knowledge_mutation")
        assert decision.admitted

    def test_automatic_publication_admitted_when_explicitly_allowed(self):
        m = manifest(automatic_scientific_publication_allowed=True)
        decision = check_manifest_governance(m, "automatic_scientific_publication")
        assert decision.admitted

    def test_canonical_activation_admitted_when_authority_not_required(self):
        m = manifest(canonical_activation_requires_human_authority=False)
        decision = check_manifest_governance(m, "canonical_activation")
        assert decision.admitted


# ── Route tests ───────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    from fastapi import FastAPI

    from app.scientific_synthesis.routes import router

    _app = FastAPI()
    _app.include_router(router)
    return TestClient(_app)


class TestGovernanceCheckRoute:
    def test_canonical_mutation_blocked(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": BASE_MANIFEST, "proposed_action": "canonical_knowledge_mutation"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "blocked"
        assert body["admitted"] is False
        assert "canonical_knowledge_mutation_allowed:false" in body["blocking_flags"]

    def test_human_review_submission_admitted(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": BASE_MANIFEST, "proposed_action": "human_review_submission"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "admitted"
        assert body["admitted"] is True
        assert body["blocking_flags"] == []

    def test_automatic_publication_blocked(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={
                "manifest": BASE_MANIFEST,
                "proposed_action": "automatic_scientific_publication",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["admitted"] is False

    def test_canonical_activation_blocked(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": BASE_MANIFEST, "proposed_action": "canonical_activation"},
        )
        assert resp.status_code == 200
        assert resp.json()["admitted"] is False

    def test_read_evidence_admitted(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": BASE_MANIFEST, "proposed_action": "read_evidence"},
        )
        assert resp.status_code == 200
        assert resp.json()["admitted"] is True

    def test_build_synthesis_admitted(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": BASE_MANIFEST, "proposed_action": "build_synthesis"},
        )
        assert resp.status_code == 200
        assert resp.json()["admitted"] is True

    def test_build_synthesis_blocked_when_evidence_incomplete(self, client):
        m = manifest(verification_state="evidence_incomplete")
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": m, "proposed_action": "build_synthesis"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["admitted"] is False
        assert "verification_state:evidence_incomplete" in body["blocking_flags"]

    def test_unknown_action_returns_422(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": BASE_MANIFEST, "proposed_action": "unknown_action"},
        )
        assert resp.status_code == 422

    def test_wrong_contract_returns_422(self, client):
        m = manifest(contract_version="wrong-v1")
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": m, "proposed_action": "read_evidence"},
        )
        assert resp.status_code == 422

    def test_malformed_fingerprint_returns_422(self, client):
        m = manifest(run_fingerprint="short")
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": m, "proposed_action": "read_evidence"},
        )
        assert resp.status_code == 422

    def test_missing_manifest_returns_422(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"proposed_action": "read_evidence"},
        )
        assert resp.status_code == 422

    def test_missing_action_returns_422(self, client):
        resp = client.post(
            "/synthesis/governance-check",
            json={"manifest": BASE_MANIFEST},
        )
        assert resp.status_code == 422
