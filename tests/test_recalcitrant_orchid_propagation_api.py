from runtime.router_fastapi import (
    queen_of_sheba_entry_material_endpoint,
    queen_of_sheba_matrix_endpoint,
    queen_of_sheba_readiness_endpoint,
    queen_of_sheba_source_endpoint,
    queen_of_sheba_vegetative_hypothesis_endpoint,
    science_router,
)


def test_propagation_routes_are_mounted_on_science_router():
    paths = {route.path for route in science_router.routes}
    expected = {
        "/api/science/propagation/queen-of-sheba/source",
        "/api/science/propagation/queen-of-sheba/matrix",
        "/api/science/propagation/queen-of-sheba/readiness",
        "/api/science/propagation/queen-of-sheba/entry-material/{material}",
        "/api/science/propagation/queen-of-sheba/hypotheses/vegetative-entry",
    }
    assert expected <= paths


def test_source_endpoint_preserves_candidate_only_source_state():
    payload = queen_of_sheba_source_endpoint()
    assert payload["doi"] == "10.1007/s11240-025-03226-9"
    assert payload["completeness"] == "abstract_verified"
    assert payload["full_text_required"] is True
    assert payload["publication_authority"] is False
    assert len(payload["digest"]) == 64


def test_matrix_endpoint_returns_six_reported_observations_without_promotion():
    payload = queen_of_sheba_matrix_endpoint()
    assert payload["taxon"] == "Thelymitra variegata"
    assert payload["candidate_only"] is True
    assert payload["row_count"] == 6
    assert payload["publication_authority"] is False
    assert payload["canonical_graph_mutation_allowed"] is False
    primary = next(row for row in payload["rows"] if row["observation_id"] == "tv-plb-001")
    assert primary["starting_material"] == "primary_protocorm"
    assert primary["quantitative_value"] == 100.0
    assert primary["reproducible_from_current_evidence"] is False


def test_entry_material_endpoint_distinguishes_direct_evidence_from_hypothesis():
    protocorm = queen_of_sheba_entry_material_endpoint("primary_protocorm")
    meristem = queen_of_sheba_entry_material_endpoint("meristem")
    assert protocorm["direct_reported_evidence"] is True
    assert protocorm["authority"] == "reported"
    assert meristem["direct_reported_evidence"] is False
    assert meristem["authority"] == "hypothesis"
    assert meristem["transfer_assessment"]["state"] == "indirect_bridge_only"
    assert meristem["transfer_assessment"]["scientific_validation"] is False


def test_unknown_entry_material_fails_closed():
    payload = queen_of_sheba_entry_material_endpoint("bulb")
    assert payload["status"] == "unknown_material"
    assert payload["scientific_validation"] is False
    assert "tuber" in payload["available_materials"]


def test_vegetative_hypothesis_is_not_davis_reported_evidence():
    payload = queen_of_sheba_vegetative_hypothesis_endpoint()
    assert payload["authority"] == "hypothesis"
    assert payload["direct_evidence_exists"] is False
    assert payload["scientific_status"] == "candidate_only_unvalidated"
    assert payload["target_material"] == "meristem"
    assert payload["publication_authority"] is False


def test_readiness_keeps_full_text_and_vegetative_evidence_blockers_visible():
    payload = queen_of_sheba_readiness_endpoint()
    assert payload["full_text_required"] is True
    assert payload["publication_authority"] is False
    assert payload["canonical_graph_mutation_allowed"] is False
    assert "meristem" in payload["unsupported_entry_materials"]
    assert any("complete Davis et al. paper" in blocker for blocker in payload["blockers"])
