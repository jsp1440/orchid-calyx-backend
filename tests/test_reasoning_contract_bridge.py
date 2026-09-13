"""Tests for reasoning_contract_bridge — Brain #103 vertical slice connector.

Proves that an oc-verification-handoff-v1 packet produced by
`calyx_brain.reasoning_contracts.build_verification_packet` can be converted
into a `BrainCandidateHandoffRequest` without any model inference or
provider API calls.

The fixture data mirrors the Phalaenopsis warm-growing acceptance scenario
from Brain PR #137 / Brain #103.
"""

from __future__ import annotations

import pytest

from app.parallel_platform.reasoning_contract_bridge import (
    verification_packet_to_handoff_request,
)

# ── Phalaenopsis warm-growing fixture (mirrors Brain PR #137 acceptance fixture) ─

_PHALAENOPSIS_PACKET = {
    "contract_version": "oc-verification-handoff-v1",
    "verification_state": "ready_for_review",
    "reasoning": {
        "contract_version": "oc-parallel-v1",
        "candidate_knowledge": {
            "candidate_id": "candidate:phal-warm-grower",
            "subject_id": "taxon:phalaenopsis",
            "predicate": "grows_optimally_at",
            "object_id": "temperature:intermediate_warm",
            "evidence_ids": [
                "evidence:phal-warm-temp-optimum",
                "evidence:phal-min-temp-threshold",
            ],
            "confidence": 0.78,
            "review_state": "candidate",
            "publication_authority": False,
        },
        "contradictions": ["candidate:phal-cool-highland"],
        "validation_pathways": ["taxonomist_review"],
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "private_chain_of_thought_stored": False,
    },
    "resolved_evidence": [
        {
            "evidence_id": "evidence:phal-warm-temp-optimum",
            "source_id": "source:rittershausen-rittershausen-2011",
            "statement": "Phalaenopsis grow optimally at intermediate-warm temperatures (25-30°C days, 18-20°C nights).",
            "provenance": ["doi:10.1234/rittershausen2011", "page:142"],
            "confidence": 0.82,
        },
        {
            "evidence_id": "evidence:phal-min-temp-threshold",
            "source_id": "source:american-orchid-society-care-guide",
            "statement": "AOS care guide recommends minimum night temperature of 16°C for Phalaenopsis.",
            "provenance": ["url:aos.org/phalaenopsis-care", "accessed:2026-09-01"],
            "confidence": 0.75,
        },
    ],
    "missing_evidence": [],
    "contradictions": ["candidate:phal-cool-highland"],
    "knowledge_gaps": [],
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
}

_DB_IDS = {
    "source_object_type": "brain_reasoning_record",
    "source_object_id": 103,
    "revision_id": 1,
    "extraction_run_id": 1,
}


def _build(**overrides):
    return verification_packet_to_handoff_request(
        _PHALAENOPSIS_PACKET,
        domain="cultivation",
        **{**_DB_IDS, **overrides},
    )


# ── Structure ──────────────────────────────────────────────────────────────────


def test_bridge_returns_handoff_request():
    req = _build()
    assert req.reasoning_id == "candidate:phal-warm-grower"
    assert req.domain == "cultivation"
    assert req.subject == "taxon:phalaenopsis"
    assert req.predicate == "grows_optimally_at"
    assert req.object_value == "temperature:intermediate_warm"
    assert abs(req.confidence - 0.78) < 1e-9


def test_bridge_concatenates_evidence_statements():
    req = _build()
    assert "Phalaenopsis grow optimally" in req.evidence_text
    assert "AOS care guide" in req.evidence_text


def test_bridge_builds_anchors_from_provenance():
    req = _build()
    assert len(req.source_anchors) == 4  # 2 evidence records × 2 provenance items each
    logical_units = [a.logical_unit for a in req.source_anchors]
    assert "doi:10.1234/rittershausen2011" in logical_units
    assert "url:aos.org/phalaenopsis-care" in logical_units


def test_bridge_anchor_locators_carry_evidence_id():
    req = _build()
    locators = {a.locator["evidence_id"] for a in req.source_anchors}
    assert "evidence:phal-warm-temp-optimum" in locators
    assert "evidence:phal-min-temp-threshold" in locators


def test_bridge_preserves_governance_flags_in_provenance():
    req = _build()
    assert req.provenance["contract_version"] == "oc-verification-handoff-v1"
    assert req.provenance["candidate_id"] == "candidate:phal-warm-grower"
    assert "candidate:phal-cool-highland" in req.provenance["contradictions"]


def test_bridge_hardcodes_governance_qualifiers():
    req = _build()
    assert req.qualifiers["human_review_required"] is True
    assert req.qualifiers["automatic_scientific_publication_allowed"] is False
    assert req.qualifiers["canonical_knowledge_mutation_allowed"] is False


def test_bridge_requires_review_and_no_publication():
    req = _build()
    assert req.display_policy == "UNKNOWN_REQUIRES_REVIEW"
    assert req.internal_use_permission is False


# ── Domain support ─────────────────────────────────────────────────────────────


def test_bridge_accepts_ecology_domain():
    req = verification_packet_to_handoff_request(
        _PHALAENOPSIS_PACKET, domain="ecology", **_DB_IDS
    )
    assert req.domain == "ecology"


def test_bridge_accepts_trait_domain():
    req = verification_packet_to_handoff_request(
        _PHALAENOPSIS_PACKET, domain="trait", **_DB_IDS
    )
    assert req.domain == "trait"


# ── Validation ────────────────────────────────────────────────────────────────


def test_bridge_rejects_wrong_contract_version():
    bad = dict(_PHALAENOPSIS_PACKET, contract_version="wrong-v1")
    with pytest.raises(ValueError, match="UNSUPPORTED_VERIFICATION_PACKET"):
        verification_packet_to_handoff_request(bad, domain="cultivation", **_DB_IDS)


def test_bridge_rejects_packet_without_human_review():
    bad = dict(_PHALAENOPSIS_PACKET, human_review_required=False)
    with pytest.raises(ValueError, match="PACKET_GOVERNANCE_INVALID"):
        verification_packet_to_handoff_request(bad, domain="cultivation", **_DB_IDS)


def test_bridge_rejects_packet_allowing_publication():
    bad = dict(_PHALAENOPSIS_PACKET, automatic_scientific_publication_allowed=True)
    with pytest.raises(ValueError, match="PACKET_GOVERNANCE_INVALID"):
        verification_packet_to_handoff_request(bad, domain="cultivation", **_DB_IDS)


def test_bridge_rejects_packet_with_no_resolved_evidence():
    no_evidence = dict(_PHALAENOPSIS_PACKET, resolved_evidence=[])
    with pytest.raises(ValueError, match="RESOLVED_EVIDENCE_REQUIRED"):
        verification_packet_to_handoff_request(
            no_evidence, domain="cultivation", **_DB_IDS
        )


def test_bridge_rejects_packet_with_empty_candidate_id():
    bad_reasoning = dict(
        _PHALAENOPSIS_PACKET["reasoning"],
        candidate_knowledge=dict(
            _PHALAENOPSIS_PACKET["reasoning"]["candidate_knowledge"],
            candidate_id="",
        ),
    )
    bad = dict(_PHALAENOPSIS_PACKET, reasoning=bad_reasoning)
    with pytest.raises(ValueError, match="CANDIDATE_ID_REQUIRED"):
        verification_packet_to_handoff_request(bad, domain="cultivation", **_DB_IDS)
