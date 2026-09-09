"""Tests for OC-COMPLETE-009 Scientific Adapter Laboratory.

Proves acceptance criteria:
- machine-readable candidate matrix exists with GloBI and ≥5 other systems
- each candidate has a reuse_decision (KEEP/PORT_CONCEPT/FEDERATE/ADAPT/REJECT/CANDIDATE_UNVERIFIED)
- bounded GloBI proof: an orchid interaction record passes all 6 pipeline stages
- at every stage: automatic_publication=False, knowledge_graph_mutation=False
- no scientific auto-promotion at any stage
- review guards satisfied on the produced document
- FAIL_NOT_NORMALIZABLE returned for records missing required fields
"""

from __future__ import annotations

from app.scientific_adapter_lab.candidate_matrix import (
    CANDIDATE_MATRIX,
    get_candidate_matrix,
    get_candidates_by_decision,
    get_integrated_candidates,
    serialize_matrix_as_json,
)
from app.scientific_adapter_lab.globi_proof import run_globi_pipeline_proof

# ---------------------------------------------------------------------------
# Fixtures: representative orchid interaction records
# ---------------------------------------------------------------------------

ORCHIS_RECORD_FULL = {
    "sourceTaxonName": "Orchis mascula",
    "sourceTaxonId": "GBIF:2843633",
    "interactionTypeName": "pollinatedBy",
    "targetTaxonName": "Bombus terrestris",
    "targetTaxonId": "GBIF:1340278",
    "referenceCitation": "Nilsson 1980 — Orchis mascula pollination study",
    "sourceCitation": "GloBI stable dataset v2026-08",
}

VANILLA_RECORD_NO_IDS = {
    "sourceTaxonName": "Vanilla planifolia",
    "interactionTypeName": "pollinatedBy",
    "targetTaxonName": "Eulaema meriana",
    # No GBIF IDs — name-only
}

RECORD_MISSING_INTERACTION = {
    "sourceTaxonName": "Dendrobium nobile",
    "targetTaxonName": "Apis mellifera",
    # No interactionTypeName/interaction_type — not normalizable
}

SNAKE_CASE_RECORD = {
    "source_taxon_name": "Ophrys apifera",
    "source_taxon_external_id": "GBIF:2848804",
    "interaction_type": "pollinatedBy",
    "target_taxon_name": "Andrena nigroaenea",
    "target_taxon_external_id": "GBIF:1356028",
    "study_citation": "Kullenberg 1961",
    "dataset_version": "globi-2026-08",
}


# ---------------------------------------------------------------------------
# Candidate matrix
# ---------------------------------------------------------------------------


def test_candidate_matrix_exists_with_at_least_six_candidates():
    assert len(CANDIDATE_MATRIX) >= 6


def test_globi_present_in_matrix():
    ids = {c["system_id"] for c in CANDIDATE_MATRIX}
    assert "globi" in ids


def test_every_candidate_has_required_fields():
    required = {"system_id", "display_name", "url", "license", "roles", "reuse_decision", "decision_rationale", "orchid_relevance"}
    for candidate in CANDIDATE_MATRIX:
        missing = required - set(candidate)
        assert not missing, f"{candidate['system_id']} missing: {missing}"


def test_every_reuse_decision_is_valid():
    valid_decisions = {
        "KEEP_AS_DEPENDENCY", "FEDERATE", "PORT_CONCEPT", "ADAPT", "REJECT", "CANDIDATE_UNVERIFIED"
    }
    for candidate in CANDIDATE_MATRIX:
        assert candidate["reuse_decision"] in valid_decisions, (
            f"{candidate['system_id']} has invalid decision: {candidate['reuse_decision']}"
        )


def test_matrix_includes_federate_and_port_concept_decisions():
    decisions = {c["reuse_decision"] for c in CANDIDATE_MATRIX}
    assert "FEDERATE" in decisions
    assert "PORT_CONCEPT" in decisions


def test_get_candidate_matrix_schema_version():
    matrix = get_candidate_matrix()
    assert matrix["schema_version"] == "oc-adapter-candidate-matrix/v1"


def test_get_candidate_matrix_graph_mutation_false():
    matrix = get_candidate_matrix()
    assert matrix["graph_mutation"] is False
    assert matrix["automatic_publication"] is False


def test_get_candidates_by_decision_federate():
    federated = get_candidates_by_decision("FEDERATE")
    assert len(federated) >= 2
    assert all(c["reuse_decision"] == "FEDERATE" for c in federated)


def test_get_integrated_candidates_includes_globi():
    integrated = get_integrated_candidates()
    ids = {c["system_id"] for c in integrated}
    assert "globi" in ids


def test_serialize_matrix_as_json_is_valid_json():
    import json

    raw = serialize_matrix_as_json()
    parsed = json.loads(raw)
    assert parsed["candidate_count"] == len(CANDIDATE_MATRIX)


def test_matrix_has_no_duplicate_system_ids():
    ids = [c["system_id"] for c in CANDIDATE_MATRIX]
    assert len(ids) == len(set(ids))


def test_globi_decision_is_federate():
    globi = next(c for c in CANDIDATE_MATRIX if c["system_id"] == "globi")
    assert globi["reuse_decision"] == "FEDERATE"


def test_globi_already_integrated():
    globi = next(c for c in CANDIDATE_MATRIX if c["system_id"] == "globi")
    assert globi["already_integrated"] is True


# ---------------------------------------------------------------------------
# GloBI proof — full record with GBIF IDs
# ---------------------------------------------------------------------------


def test_globi_proof_passes_for_full_orchid_record():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    assert proof["verdict"] in ("PASS", "PASS_WITH_NOTES"), proof.get("reason")


def test_globi_proof_stage_names_present():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    assert set(proof["stages"]) >= {
        "source", "normalization", "taxon_reconciliation",
        "evidence_provenance", "review_contract", "kg_candidate_contract",
    }


def test_globi_proof_no_automatic_publication_at_top_level():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    assert proof["automatic_publication"] is False


def test_globi_proof_no_kg_mutation_at_top_level():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    assert proof["knowledge_graph_mutation"] is False


def test_globi_proof_not_promoted_to_kg():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    assert proof["summary"]["promoted_to_kg"] is False


# ---------------------------------------------------------------------------
# Stage 1: SOURCE
# ---------------------------------------------------------------------------


def test_source_stage_preserves_raw_record():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["source"]
    assert stage["stage"] == "SOURCE"
    assert stage["raw_record"]["sourceTaxonName"] == "Orchis mascula"
    assert stage["automatic_publication"] is False
    assert stage["knowledge_graph_mutation"] is False


# ---------------------------------------------------------------------------
# Stage 2: NORMALIZATION
# ---------------------------------------------------------------------------


def test_normalization_stage_resolves_camel_case():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["normalization"]
    assert stage["stage"] == "NORMALIZATION"
    assert stage["normalizable"] is True
    assert stage["source_taxon_name"] == "Orchis mascula"
    assert stage["interaction_type"] == "pollinatedBy"


def test_normalization_stage_resolves_snake_case():
    proof = run_globi_pipeline_proof(SNAKE_CASE_RECORD, dataset_version="globi-2026-08")
    stage = proof["stages"]["normalization"]
    assert stage["normalizable"] is True
    assert stage["source_taxon_name"] == "Ophrys apifera"


def test_normalization_stage_no_auto_publication():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    assert proof["stages"]["normalization"]["automatic_publication"] is False


# ---------------------------------------------------------------------------
# Stage 3: TAXON_RECONCILIATION
# ---------------------------------------------------------------------------


def test_taxon_reconciliation_matched_for_gbif_ids():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["taxon_reconciliation"]
    assert stage["stage"] == "TAXON_RECONCILIATION"
    assert stage["source_taxon"]["reconciliation_status"] == "MATCHED"
    assert stage["source_taxon"]["backbone"] == "GBIF"
    assert stage["target_taxon"]["reconciliation_status"] == "MATCHED"
    assert stage["both_reconciled"] is True
    assert stage["automatic_publication"] is False
    assert stage["knowledge_graph_mutation"] is False


def test_taxon_reconciliation_unmatched_for_name_only():
    proof = run_globi_pipeline_proof(VANILLA_RECORD_NO_IDS, dataset_version="globi-2026-08")
    stage = proof["stages"]["taxon_reconciliation"]
    assert stage["source_taxon"]["reconciliation_status"] == "UNMATCHED"
    assert stage["both_reconciled"] is False


def test_taxon_reconciliation_further_review_flagged():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["taxon_reconciliation"]
    assert stage["further_reconciliation_required_before_scientific_review"] is True


# ---------------------------------------------------------------------------
# Stage 4: EVIDENCE_PROVENANCE
# ---------------------------------------------------------------------------


def test_evidence_provenance_stage_carries_dataset_version():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["evidence_provenance"]
    assert stage["stage"] == "EVIDENCE_PROVENANCE"
    assert stage["dataset_version"] == "globi-2026-08"
    assert stage["provider"] == "Global Biotic Interactions"
    assert stage["automatic_publication"] is False
    assert stage["knowledge_graph_mutation"] is False


def test_evidence_provenance_traceable_when_citation_present():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["evidence_provenance"]
    assert stage["has_study_citation"] is True
    assert stage["traceable_to_reproducible_source"] is True


def test_evidence_provenance_contract_name():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    assert proof["stages"]["evidence_provenance"]["provenance_contract"] == (
        "globi-canonical-dataset-review-bound-v1"
    )


# ---------------------------------------------------------------------------
# Stage 5: REVIEW_CONTRACT
# ---------------------------------------------------------------------------


def test_review_contract_guards_all_satisfied():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["review_contract"]
    assert stage["guards_satisfied"] is True, stage.get("defects")


def test_review_contract_verification_state_unverified():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["review_contract"]
    assert stage["verification_state"] == "UNVERIFIED"


def test_review_contract_no_auto_publication_guard():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    guards = proof["stages"]["review_contract"]["guards"]
    assert guards["automatic_publication_false"] is True


def test_review_contract_no_kg_mutation_guard():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    guards = proof["stages"]["review_contract"]["guards"]
    assert guards["knowledge_graph_mutation_false"] is True


def test_review_contract_document_is_metadata_only():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["review_contract"]
    assert stage["display_policy"] == "METADATA_ONLY"


# ---------------------------------------------------------------------------
# Stage 6: KG_CANDIDATE_CONTRACT
# ---------------------------------------------------------------------------


def test_kg_candidate_eligible_for_review():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["kg_candidate_contract"]
    assert stage["candidate_eligible_for_review"] is True, stage.get("defects")


def test_kg_candidate_not_promoted():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["kg_candidate_contract"]
    assert stage["promoted_to_kg"] is False


def test_kg_candidate_promotion_requires_review():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    stage = proof["stages"]["kg_candidate_contract"]
    assert "review" in stage["promotion_requires"].lower()


# ---------------------------------------------------------------------------
# Non-normalizable records
# ---------------------------------------------------------------------------


def test_missing_interaction_type_yields_fail_not_normalizable():
    proof = run_globi_pipeline_proof(RECORD_MISSING_INTERACTION, dataset_version="globi-2026-08")
    assert proof["verdict"] == "FAIL_NOT_NORMALIZABLE"
    assert proof["automatic_publication"] is False
    assert proof["knowledge_graph_mutation"] is False


def test_missing_interaction_type_has_no_review_stage():
    proof = run_globi_pipeline_proof(RECORD_MISSING_INTERACTION, dataset_version="globi-2026-08")
    assert "review_contract" not in proof.get("stages", {})


# ---------------------------------------------------------------------------
# Summary block
# ---------------------------------------------------------------------------


def test_summary_block_present():
    proof = run_globi_pipeline_proof(ORCHIS_RECORD_FULL, dataset_version="globi-2026-08")
    summary = proof["summary"]
    expected_keys = {
        "normalizable", "either_taxon_reconciled", "both_taxa_reconciled",
        "traceable_to_source", "review_guards_satisfied", "eligible_for_review", "promoted_to_kg",
    }
    assert expected_keys <= set(summary)


def test_summary_promoted_to_kg_always_false():
    for record in [ORCHIS_RECORD_FULL, VANILLA_RECORD_NO_IDS, SNAKE_CASE_RECORD]:
        proof = run_globi_pipeline_proof(record, dataset_version="globi-2026-08")
        if "summary" in proof:
            assert proof["summary"]["promoted_to_kg"] is False


# ---------------------------------------------------------------------------
# Non-promoted at every non-normalizable path too
# ---------------------------------------------------------------------------


def test_non_normalizable_still_has_no_kg_mutation():
    proof = run_globi_pipeline_proof(RECORD_MISSING_INTERACTION, dataset_version="globi-2026-08")
    assert proof["knowledge_graph_mutation"] is False
