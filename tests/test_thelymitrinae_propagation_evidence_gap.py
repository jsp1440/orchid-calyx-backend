from runtime.thelymitrinae_propagation_evidence_gap import (
    acquisition_leads,
    acquisition_matrix,
    evidence_ladder,
    targeted_search_state,
)


def test_search_nonretrieval_is_not_evidence_of_absence():
    state = targeted_search_state()
    assert state["answer_state"] == "same_genus_ex_situ_success_documented_method_unresolved"
    assert state["same_genus_ex_situ_propagation_documented"] is True
    assert state["same_genus_method_resolved"] is False
    assert state["direct_same_subtribe_vegetative_evidence_verified"] is False
    assert state["evidence_of_absence_claimed"] is False
    assert state["search_nonretrieval_means_absence"] is False


def test_same_genus_recovery_plan_is_critical_acquisition_lead():
    leads = {lead.lead_id: lead for lead in acquisition_leads()}
    lead = leads["dcceew-1999-thelymitra-manginii-recovery"]
    assert lead.source_type == "government_recovery_plan"
    assert lead.acquisition_priority == "critical"
    assert "Thelymitra manginii" in lead.focal_taxa
    assert "successfully propagated" in lead.retrievable_fact
    assert lead.direct_vegetative_evidence_verified is False


def test_thelymitra_reference_book_remains_critical_primary_reference_trail():
    state = targeted_search_state()
    leads = {lead.lead_id: lead for lead in acquisition_leads()}
    assert "yam-arditti-micropropagation-thelymitra" in state["highest_priority_next_sources"]
    lead = leads["yam-arditti-micropropagation-thelymitra"]
    assert lead.source_type == "specialist_reference_book"
    assert lead.acquisition_priority == "critical"
    assert "Thelymitra" in lead.focal_taxa
    assert lead.direct_vegetative_evidence_verified is False


def test_evidence_ladder_preserves_same_genus_success_without_method_claim():
    ladder = evidence_ladder()
    assert ladder["levels"][0]["scope"] == "same species"
    assert ladder["levels"][1]["scope"] == "same genus Thelymitra"
    assert "propagation_method_unresolved" in ladder["levels"][1]["state"]
    assert ladder["levels"][2]["scope"] == "same subtribe Thelymitrinae"
    assert "Diuris_longifolia" in ladder["levels"][3]["state"]
    assert ladder["automatic_protocol_selection_allowed"] is False
    assert ladder["destructive_tuber_sampling_priority"] == "defer_until_lower_risk_routes_reviewed"
    assert ladder["publication_authority"] is False


def test_acquisition_matrix_is_deterministic_and_non_authoritative():
    rows = acquisition_matrix()
    assert len(rows) == 3
    assert all(len(row["lead_sha256"]) == 64 for row in rows)
    assert all(row["direct_vegetative_evidence_verified"] is False for row in rows)
    assert all(row["publication_authority"] is False for row in rows)
