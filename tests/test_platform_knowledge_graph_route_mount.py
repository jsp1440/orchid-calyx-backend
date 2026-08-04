from app.routers.knowledge_graph import router


def _route_methods():
    return {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }


def test_platform_and_traversal_routes_are_mounted_with_expected_methods():
    routes = _route_methods()

    expected = {
        ("/api/knowledge-graph/node/{node_id}", "GET"),
        ("/api/knowledge-graph/taxon/{taxon_id}", "GET"),
        ("/api/knowledge-graph/genus/{genus_name}", "GET"),
        ("/api/knowledge-graph/quality", "GET"),
        ("/api/knowledge-graph/full-integration", "GET"),
        ("/api/platform/knowledge-graph/full-integration", "GET"),
        ("/api/platform/knowledge-graph/controlled-dry-run", "POST"),
        ("/api/platform/knowledge-graph/persisted-audit", "GET"),
        ("/api/platform/knowledge-graph/deployment-preflight", "GET"),
        ("/api/platform/knowledge-graph/dry-runs", "POST"),
        ("/api/platform/knowledge-graph/dry-runs/{run_id}", "GET"),
        ("/api/platform/knowledge-graph/dry-runs/{run_id}/resume", "POST"),
        ("/api/platform/knowledge-graph/dry-runs/{run_id}/cancel", "POST"),
    }

    assert expected <= routes
