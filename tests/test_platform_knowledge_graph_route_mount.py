from app.routers.knowledge_graph import router


def test_platform_and_traversal_routes_are_mounted_together():
    paths = {route.path for route in router.routes}

    assert "/api/knowledge-graph/taxon/{taxon_id}" in paths
    assert "/api/knowledge-graph/quality" in paths

    assert "/api/platform/knowledge-graph/full-integration" in paths
    assert "/api/platform/knowledge-graph/controlled-dry-run" in paths
    assert "/api/platform/knowledge-graph/persisted-audit" in paths
    assert "/api/platform/knowledge-graph/dry-runs" in paths
    assert "/api/platform/knowledge-graph/dry-runs/{run_id}" in paths
    assert "/api/platform/knowledge-graph/dry-runs/{run_id}/resume" in paths
    assert "/api/platform/knowledge-graph/dry-runs/{run_id}/cancel" in paths
