import json

from scripts.oc_firecrawl_federation_pilot import SOURCES


def test_pilot_targets_are_bounded_and_specific():
    assert set(SOURCES) == {"powo", "wfo"}
    assert SOURCES["powo"]["search"] == "Phragmipedium"
    assert SOURCES["wfo"]["search"] == "Phragmipedium"
    assert SOURCES["powo"]["root_url"].startswith("https://")
    assert SOURCES["wfo"]["root_url"].startswith("https://")


def test_pilot_source_definitions_are_json_serializable():
    json.dumps(SOURCES)


def test_source_surface_discovery_is_opt_in(monkeypatch):
    from scripts.oc_firecrawl_federation_pilot import parse_args

    monkeypatch.setattr("sys.argv", ["pilot"])
    args = parse_args()

    assert args.discover_source_surfaces is False
