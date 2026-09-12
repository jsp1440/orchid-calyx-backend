"""Tests for RunEvidenceManifest — Brain #103 vertical slice step 10.

A RunEvidenceManifest is an immutable, sha256-fingerprinted record of one
evidence-to-decision research run. It carries:
  - the verification packet (evidence, contradictions, gaps, governance flags)
  - the review record (decision, rationale, reviewer identity)
  - the epistemic memory digest (non-canonical staging record)
  - a run fingerprint that is deterministic across repeated calls

These tests prove the manifest contract without any model inference.
They use only deterministic fixture data and the canonical
app.scientific_synthesis contracts.

Relationship to canonical modules:
  - Reuses app.scientific_synthesis.service.fingerprint (sha256 canonical JSON)
  - Reuses app.scientific_synthesis.run_manifest.build_run_evidence_manifest
  - Does NOT call any paid external model API
  - Does NOT mutate production state or taxonomy
"""

from __future__ import annotations

from app.scientific_synthesis.run_manifest import (
    MANIFEST_VERSION,
    build_run_evidence_manifest,
)

# ── Minimal fixture data (deterministic, no real sources) ─────────────────────

_VERIFICATION_PACKET = {
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
                "evidence:phal-min-temp",
            ],
            "confidence": 0.78,
            "review_state": "candidate",
        },
        "contradictions": ["candidate:phal-cool-tolerant"],
        "validation_pathways": ["taxonomist_review"],
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "private_chain_of_thought_stored": False,
    },
    "resolved_evidence": [
        {
            "evidence_id": "evidence:phal-warm-temp-optimum",
            "source_id": "source:rittershausen-2011",
            "statement": "Phalaenopsis grow optimally at 25-30°C days, 18-20°C nights.",
            "provenance": ["doi:10.1234/rittershausen2011", "page:142"],
            "confidence": 0.82,
        },
        {
            "evidence_id": "evidence:phal-min-temp",
            "source_id": "source:aos-care-guide",
            "statement": "AOS recommends minimum night temperature of 16°C.",
            "provenance": ["url:aos.org/phalaenopsis-care"],
            "confidence": 0.75,
        },
    ],
    "missing_evidence": [],
    "contradictions": ["candidate:phal-cool-tolerant"],
    "validation_pathways": ["taxonomist_review"],
    "knowledge_gaps": [],
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
}

_REVIEW_RECORD = {
    "contract_version": "oc-review-decision-record-v1",
    "decision_id": "review:phal-warm-2026-09",
    "candidate_id": "candidate:phal-warm-grower",
    "reviewer_id": "reviewer:fcos-orchids-principal",
    "review_authority_id": "authority:fcos-orchids-science",
    "review_decision": "accept_for_staging",
    "rationale": "Warm claim supported; cool-tolerant evidence preserved as contradiction.",
    "source_packet_digest": "a" * 64,
    "resolved_evidence_ids": [
        "evidence:phal-min-temp",
        "evidence:phal-warm-temp-optimum",
    ],
    "contradictions": ["candidate:phal-cool-tolerant"],
    "knowledge_gap_count": 0,
    "previous_record_id": None,
    "learning_state": "reviewed_staging_candidate",
    "status": "recorded_for_governed_persistence",
    "append_only": True,
    "human_review_required": True,
    "automatic_execution_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
    "scientific_publication_allowed": False,
    "private_chain_of_thought_stored": False,
}

_EPISTEMIC_MEMORY = {
    "contract_version": "oc-reviewed-epistemic-memory-v1",
    "memory_entry_id": "memory:phal-warm-2026-09",
    "taxonomy_snapshot_id": "hassler:2026-09",
    "candidate_id": "candidate:phal-warm-grower",
    "source_decision_id": "review:phal-warm-2026-09",
    "source_packet_digest": "a" * 64,
    "reviewer_id": "reviewer:fcos-orchids-principal",
    "review_authority_id": "authority:fcos-orchids-science",
    "review_decision": "accept_for_staging",
    "epistemic_state": "reviewed_candidate",
    "resolved_evidence_ids": [
        "evidence:phal-min-temp",
        "evidence:phal-warm-temp-optimum",
    ],
    "contradictions": ["candidate:phal-cool-tolerant"],
    "previous_record_id": None,
    "append_only": True,
    "automatic_execution_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
    "scientific_publication_allowed": False,
    "canonical_activation_requires_human_authority": True,
    "private_chain_of_thought_stored": False,
}


def _manifest(**overrides):
    return build_run_evidence_manifest(
        run_id="run:phal-2026-09-12",
        research_question="Which traits distinguish cool-growing from warm-growing Phalaenopsis?",
        taxon_id="taxon:phalaenopsis",
        taxonomy_snapshot_id="hassler:2026-09",
        verification_packets=(_VERIFICATION_PACKET,),
        review_records=(_REVIEW_RECORD,),
        epistemic_memory_entries=(_EPISTEMIC_MEMORY,),
        **overrides,
    )


# ── Structure tests ───────────────────────────────────────────────────────────


def test_manifest_has_required_fields():
    m = _manifest()
    assert m["contract_version"] == MANIFEST_VERSION
    assert m["run_id"] == "run:phal-2026-09-12"
    assert m["taxon_id"] == "taxon:phalaenopsis"
    assert m["taxonomy_snapshot_id"] == "hassler:2026-09"
    assert isinstance(m["run_fingerprint"], str) and len(m["run_fingerprint"]) == 64
    assert isinstance(m["created_at_utc"], str)


def test_manifest_preserves_governance_flags():
    m = _manifest()
    assert m["human_review_required"] is True
    assert m["automatic_scientific_publication_allowed"] is False
    assert m["canonical_knowledge_mutation_allowed"] is False
    assert m["canonical_activation_requires_human_authority"] is True
    assert m["immutable"] is True


def test_manifest_embeds_evidence_count():
    m = _manifest()
    assert m["resolved_evidence_count"] == 2
    assert m["missing_evidence_count"] == 0
    assert m["knowledge_gap_count"] == 0


def test_manifest_embeds_contradictions():
    m = _manifest()
    assert "candidate:phal-cool-tolerant" in m["contradictions"]


def test_manifest_embeds_review_decision():
    m = _manifest()
    assert m["review_decision"] == "accept_for_staging"
    assert m["epistemic_state"] == "reviewed_candidate"


# ── Determinism tests ─────────────────────────────────────────────────────────


def test_manifest_is_deterministic():
    assert _manifest()["run_fingerprint"] == _manifest()["run_fingerprint"]


def test_manifest_fingerprint_changes_with_content():
    m1 = _manifest()
    m2 = build_run_evidence_manifest(
        run_id="run:phal-2026-09-12",
        research_question="Different question.",
        taxon_id="taxon:phalaenopsis",
        taxonomy_snapshot_id="hassler:2026-09",
        verification_packets=(_VERIFICATION_PACKET,),
        review_records=(_REVIEW_RECORD,),
        epistemic_memory_entries=(_EPISTEMIC_MEMORY,),
    )
    assert m1["run_fingerprint"] != m2["run_fingerprint"]


# ── Validation tests ──────────────────────────────────────────────────────────


def test_manifest_requires_run_id():
    try:
        build_run_evidence_manifest(
            run_id="",
            research_question="Q",
            taxon_id="taxon:phalaenopsis",
            taxonomy_snapshot_id="hassler:2026-09",
            verification_packets=(_VERIFICATION_PACKET,),
            review_records=(),
            epistemic_memory_entries=(),
        )
    except ValueError as exc:
        assert "RUN_ID_REQUIRED" in str(exc)
    else:
        raise AssertionError("empty run_id was accepted")


def test_manifest_requires_taxon_id():
    try:
        build_run_evidence_manifest(
            run_id="run:x",
            research_question="Q",
            taxon_id="",
            taxonomy_snapshot_id="hassler:2026-09",
            verification_packets=(_VERIFICATION_PACKET,),
            review_records=(),
            epistemic_memory_entries=(),
        )
    except ValueError as exc:
        assert "TAXON_ID_REQUIRED" in str(exc)
    else:
        raise AssertionError("empty taxon_id was accepted")


def test_manifest_requires_at_least_one_verification_packet():
    try:
        build_run_evidence_manifest(
            run_id="run:x",
            research_question="Q",
            taxon_id="taxon:phalaenopsis",
            taxonomy_snapshot_id="hassler:2026-09",
            verification_packets=(),
            review_records=(),
            epistemic_memory_entries=(),
        )
    except ValueError as exc:
        assert "VERIFICATION_PACKET_REQUIRED" in str(exc)
    else:
        raise AssertionError("empty verification_packets was accepted")


def test_manifest_rejects_wrong_packet_version():
    bad_packet = dict(_VERIFICATION_PACKET, contract_version="wrong-version")
    try:
        build_run_evidence_manifest(
            run_id="run:x",
            research_question="Q",
            taxon_id="taxon:phalaenopsis",
            taxonomy_snapshot_id="hassler:2026-09",
            verification_packets=(bad_packet,),
            review_records=(),
            epistemic_memory_entries=(),
        )
    except ValueError as exc:
        assert "UNSUPPORTED_VERIFICATION_PACKET" in str(exc)
    else:
        raise AssertionError("wrong contract_version was accepted")


def test_manifest_rejects_packet_without_human_review_required():
    bad_packet = dict(_VERIFICATION_PACKET, human_review_required=False)
    try:
        build_run_evidence_manifest(
            run_id="run:x",
            research_question="Q",
            taxon_id="taxon:phalaenopsis",
            taxonomy_snapshot_id="hassler:2026-09",
            verification_packets=(bad_packet,),
            review_records=(),
            epistemic_memory_entries=(),
        )
    except ValueError as exc:
        assert "PACKET_GOVERNANCE_INVALID" in str(exc)
    else:
        raise AssertionError("packet without human_review_required was accepted")


# ── Missing evidence round-trip ───────────────────────────────────────────────


def test_manifest_with_missing_evidence_records_gap_count():
    packet_with_gap = dict(
        _VERIFICATION_PACKET,
        verification_state="evidence_incomplete",
        missing_evidence=[
            {"evidence_id": "evidence:missing-study", "epistemic_state": "unknown"}
        ],
        knowledge_gaps=[
            {
                "gap_type": "missing_evidence",
                "evidence_id": "evidence:missing-study",
                "epistemic_state": "unknown",
            }
        ],
    )
    m = build_run_evidence_manifest(
        run_id="run:phal-gap",
        research_question="Q",
        taxon_id="taxon:phalaenopsis",
        taxonomy_snapshot_id="hassler:2026-09",
        verification_packets=(packet_with_gap,),
        review_records=(),
        epistemic_memory_entries=(),
    )
    assert m["missing_evidence_count"] == 1
    assert m["knowledge_gap_count"] == 1
    assert m["verification_state"] == "evidence_incomplete"
