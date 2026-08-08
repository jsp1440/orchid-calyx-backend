from runtime.router_fastapi import (
    queen_of_sheba_evidence_ladder_endpoint,
    queen_of_sheba_thelymitrinae_acquisition_endpoint,
    queen_of_sheba_thelymitrinae_search_state_endpoint,
    science_router,
)


def test_thelymitrinae_evidence_routes_are_mounted():
    paths = {route.path for route in science_router.routes}
    assert "/api/science/propagation/queen-of-sheba/evidence/thelymitrinae/search-state" in paths
    assert "/api/science/propagation/queen-of-sheba/evidence/thelymitrinae/acquisition-matrix" in paths
    assert "/api/science/propagation/queen-of-sheba/evidence/ladder" in paths


def test_same_genus_success_is_visible_without_method_upgrade():
    state = queen_of_sheba_thelymitrinae_search_state_endpoint()
    assert state["same_genus_ex_situ_propagation_documented"] is True
    assert state["same_genus_method_resolved"] is False
    assert state["direct_same_subtribe_vegetative_evidence_verified"] is False
    assert state["publication_authority"] is False


def test_acquisition_api_preserves_government_recovery_plan_as_nonvegetative_lead():
    payload = queen_of_sheba_thelymitrinae_acquisition_endpoint()
    assert payload["row_count"] == 3
    recovery = next(
        row for row in payload["rows"] if row["lead_id"] == "dcceew-1999-thelymitra-manginii-recovery"
    )
    assert recovery["source_type"] == "government_recovery_plan"
    assert recovery["direct_vegetative_evidence_verified"] is False
    assert payload["canonical_graph_mutation_allowed"] is False


def test_evidence_ladder_keeps_same_genus_separate_from_same_species_and_diuris():
    ladder = queen_of_sheba_evidence_ladder_endpoint()
    scopes = [level["scope"] for level in ladder["levels"]]
    assert scopes[:4] == [
        "same species",
        "same genus Thelymitra",
        "same subtribe Thelymitrinae",
        "proximal core Diurideae",
    ]
    assert ladder["automatic_protocol_selection_allowed"] is False
    assert ladder["knowledge_graph_mutation_authorized"] is False
