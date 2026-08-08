from runtime.thelymitrinae_propagation_evidence_gap import (
    acquisition_leads,
    acquisition_matrix,
    evidence_ladder,
    targeted_search_state,
)


def test_search_nonretrieval_is_not_evidence_of_absence():
    state = targeted_search_state()
    assert state["answer_state"] == "unresolved_source_acquisition_required"
    assert state["direct_same_subtribe_vegetative_evidence_verified"] is False
    assert state["evidence_of_absence_claimed"] is False
    assert state["search_nonretrieval_means_absence"] is False


def test_thelymitra_reference_book_is_highest_priority_acquisition_lead():
    state = targeted_search_state()
    leads = {lead.lead_id: lead for lead in acquisition_leads()}
    lead = leads[state["highest_priority_next_source"]]
    assert lead.source_type == "specialist_reference_book"
    assert lead.acquisition_priority == "critical"
    assert "Thelymitra" in lead.focal_taxa
    assert lead.direct_vegetative_evidence_verified is False


def test_evidence_ladder_preserves_proximity_without_protocol_selection():
    ladder = evidence_ladder()
    assert ladder["levels"][0]["scope"] == "same species"
    assert ladder["levels"][1]["scope"] == "same subtribe Thelymitrinae"
    assert "Diuris_longifolia" in ladder["levels"][2]["state"]
    assert ladder["automatic_protocol_selection_allowed"] is False
    assert ladder["destructive_tuber_sampling_priority"] == "defer_until_lower_risk_routes_reviewed"
    assert ladder["publication_authority"] is False


def test_acquisition_matrix_is_deterministic_and_non_authoritative():
    rows = acquisition_matrix()
    assert len(rows) == 2
    assert all(len(row["lead_sha256"]) == 64 for row in rows)
    assert all(row["direct_vegetative_evidence_verified"] is False for row in rows)
    assert all(row["publication_authority"] is False for row in rows)
