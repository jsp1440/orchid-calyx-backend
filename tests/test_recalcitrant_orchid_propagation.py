from runtime.recalcitrant_orchid_propagation import (
    EvidenceAuthority,
    MaterialClass,
    evidence_support_for_entry_material,
    protocol_matrix,
    queen_of_sheba_observations,
    queen_of_sheba_readiness,
    queen_of_sheba_source,
    transfer_candidate_score,
    vegetative_entry_hypothesis,
)


def test_queen_of_sheba_source_is_abstract_level_and_requires_full_text():
    source = queen_of_sheba_source()
    assert source.authority == EvidenceAuthority.REPORTED
    assert source.full_text_required is True
    assert source.doi == "10.1007/s11240-025-03226-9"


def test_reported_plb_induction_is_not_promoted_to_meristem_evidence():
    primary = evidence_support_for_entry_material(MaterialClass.PRIMARY_PROTOCORM)
    meristem = evidence_support_for_entry_material(MaterialClass.MERISTEM)
    assert primary["direct_reported_evidence"] is True
    assert meristem["direct_reported_evidence"] is False
    assert meristem["authority"] == "hypothesis"


def test_hypothesis_preserves_governance_boundary():
    hypothesis = vegetative_entry_hypothesis()
    assert hypothesis.direct_evidence_exists is False
    assert hypothesis.scientific_status == "candidate_only_unvalidated"
    assert any("Do not destructively sample" in item for item in hypothesis.safeguards)


def test_protocol_matrix_preserves_missing_details_and_100_percent_result():
    rows = protocol_matrix()
    induction = next(row for row in rows if row["observation_id"] == "tv-plb-001")
    assert induction["quantitative_value"] == 100.0
    assert induction["reproducible_from_current_evidence"] is False
    assert "sterilization_protocol" in induction["missing_details"]


def test_structural_evidence_score_is_not_success_probability():
    score = transfer_candidate_score(MaterialClass.MERISTEM)
    assert score["state"] == "indirect_bridge_only"
    assert score["evidence_proximity_score"] < 0.5
    assert score["scientific_validation"] is False
    assert "not success probability" in score["score_semantics"]


def test_readiness_blocks_reproduction_until_full_text_extraction():
    readiness = queen_of_sheba_readiness()
    assert readiness.full_text_required is True
    assert readiness.publication_authority is False
    assert readiness.canonical_graph_mutation_allowed is False
    assert "meristem" in readiness.unsupported_entry_materials
    assert len(queen_of_sheba_observations()) == readiness.observation_count


def test_digests_are_deterministic():
    first = [row["digest"] for row in protocol_matrix()]
    second = [row["digest"] for row in protocol_matrix()]
    assert first == second
