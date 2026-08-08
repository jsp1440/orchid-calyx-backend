from runtime.router_fastapi import science_router


def test_diuris_comparator_routes_are_mounted():
    paths = {route.path for route in science_router.routes}
    assert "/api/science/propagation/queen-of-sheba/comparators/diuris/source" in paths
    assert "/api/science/propagation/queen-of-sheba/comparators/diuris/matrix" in paths
    assert "/api/science/propagation/queen-of-sheba/comparators/diuris/bridge" in paths


def test_diuris_bridge_functions_remain_nonpublication_authoritative():
    from runtime.router_fastapi import (
        queen_of_sheba_diuris_bridge_endpoint,
        queen_of_sheba_diuris_matrix_endpoint,
        queen_of_sheba_diuris_source_endpoint,
    )

    source = queen_of_sheba_diuris_source_endpoint()
    matrix = queen_of_sheba_diuris_matrix_endpoint()
    bridge = queen_of_sheba_diuris_bridge_endpoint()

    assert source["taxon"] == "Diuris longifolia"
    assert source["direct_thelymitra_evidence"] is False
    assert source["publication_authority"] is False

    assert matrix["row_count"] == 3
    assert matrix["direct_thelymitra_evidence"] is False
    assert matrix["canonical_graph_mutation_allowed"] is False

    assert bridge["phylogenetic"]["same_subtribe"] is False
    assert bridge["phylogenetic"]["method_transfer_validated"] is False
    assert bridge["non_destructive"]["recommended_thelymitra_explant"] is None
    assert bridge["publication_authority"] is False
