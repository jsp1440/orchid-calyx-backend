from __future__ import annotations

from app.calyx_conversation import continuum_context


def test_environmental_facts_surface_canonical_rainfall_and_temperature_fields():
    graph = {
        "nodes": [
            {
                "canonical_key": "taxon:cymbidium-example",
                "properties": {
                    "annual_precipitation_mm": 1450,
                    "mean_temperature_c": 14.2,
                    "flower_color": "green",
                },
            }
        ],
        "edges": [
            {
                "edge_type": "OCCURS_IN_CLIMATE",
                "properties": {"precipitation_seasonality": 62.0},
            }
        ],
    }

    facts = continuum_context._environmental_facts(graph)
    keys = {fact["key"] for fact in facts}

    assert "annual_precipitation_mm" in keys
    assert "mean_temperature_c" in keys
    assert "precipitation_seasonality" in keys
    assert "flower_color" not in keys
