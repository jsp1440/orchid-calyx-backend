from __future__ import annotations

import pytest

from app.calyx_orchestrator.scientific_agents import (
    PROHIBITED_SCIENTIFIC_ACTIONS,
    SCIENTIFIC_ROLE_REGISTRY,
    ScientificAgentRole,
    ScientificResult,
    scientific_role_snapshot,
)


def test_all_phase_2_roles_are_registered() -> None:
    assert set(SCIENTIFIC_ROLE_REGISTRY) == set(ScientificAgentRole)
    assert len(SCIENTIFIC_ROLE_REGISTRY) == 11


def test_role_snapshot_exposes_governance_contract() -> None:
    snapshot = scientific_role_snapshot()
    assert len(snapshot) == 11
    assert all(item["required_evidence"] for item in snapshot)
    assert all(item["requires_human_approval"] is True for item in snapshot)
    assert all("publish_scientific_knowledge" in item["prohibited_actions"] for item in snapshot)


def test_scientific_result_requires_provenance() -> None:
    result = ScientificResult(
        role=ScientificAgentRole.ATLAS_ENGINEER,
        canonical_taxon_identity="taxon:123",
        provenance=(),
        evidence={
            "occurrence_identity": "occ:1",
            "canonical_taxon_identity": "taxon:123",
            "coordinates": [35.3, -120.8],
            "license": "CC-BY",
            "provenance": ["fixture"],
        },
    )
    with pytest.raises(ValueError, match="PROVENANCE_REQUIRED"):
        result.validate()


def test_scientific_result_rejects_missing_required_evidence() -> None:
    result = ScientificResult(
        role=ScientificAgentRole.TAXONOMY_ENGINEER,
        canonical_taxon_identity=None,
        provenance=("fixture:hassler",),
        evidence={"release_identity": "WorldOrchids-26-08"},
    )
    with pytest.raises(ValueError, match="REQUIRED_EVIDENCE_MISSING"):
        result.validate()


def test_scientific_result_rejects_prohibited_action() -> None:
    result = ScientificResult(
        role=ScientificAgentRole.EVIDENCE_PROVENANCE_ENGINEER,
        canonical_taxon_identity="taxon:123",
        provenance=("fixture:evidence",),
        evidence={
            "source_identity": "source:1",
            "claim_lineage": ["claim:1"],
            "confidence": 0.9,
            "review_hash": "abc123",
            "provenance": ["fixture:evidence"],
        },
        requested_action="publish_scientific_knowledge",
    )
    assert result.requested_action in PROHIBITED_SCIENTIFIC_ACTIONS
    with pytest.raises(PermissionError, match="SCIENTIFIC_ACTION_PROHIBITED"):
        result.validate()


def test_valid_scientific_result_passes() -> None:
    result = ScientificResult(
        role=ScientificAgentRole.CONSERVATION_ENGINEER,
        canonical_taxon_identity="taxon:laelia-anceps",
        provenance=("fixture:conservation",),
        evidence={
            "taxon_identity": "taxon:laelia-anceps",
            "status_source": "fixture-status",
            "threats": ["habitat loss"],
            "actions": ["habitat protection"],
            "provenance": ["fixture:conservation"],
        },
        confidence=0.8,
    )
    result.validate()
