from app.scientific_interpretation.routes import router


def test_scientific_synthesis_routes_are_mounted_under_interpretation_api():
    paths = {route.path for route in router.routes}

    assert "/api/scientific-interpretation/synthesis/validate" in paths
    assert "/api/scientific-interpretation/synthesis/health" in paths
