from app.calyx_conversation.occurrence_query import parse_occurrence_filter


def test_parses_country_and_above_elevation():
    parsed = parse_occurrence_filter("List all orchids in Ecuador that occur above 3000 meters")
    assert parsed is not None
    assert parsed.country == "Ecuador"
    assert parsed.elevation_mode == "above"
    assert parsed.elevation_min_m == 3000.0


def test_parses_country_and_below_elevation():
    parsed = parse_occurrence_filter("List all orchids in Ecuador below 1500 metres")
    assert parsed is not None
    assert parsed.country == "Ecuador"
    assert parsed.elevation_mode == "below"
    assert parsed.elevation_max_m == 1500.0


def test_parses_between_range_order_independently():
    parsed = parse_occurrence_filter("Which orchids in Ecuador occur between 4000 and 3000 m?")
    assert parsed is not None
    assert parsed.elevation_mode == "between"
    assert parsed.elevation_min_m == 3000.0
    assert parsed.elevation_max_m == 4000.0


def test_parses_exact_elevation_as_range_containment_query():
    parsed = parse_occurrence_filter("List orchids in Ecuador at 10000 meters")
    assert parsed is not None
    assert parsed.country == "Ecuador"
    assert parsed.elevation_mode == "at"
    assert parsed.target_elevation_m == 10000.0


def test_requires_both_country_and_elevation_constraint():
    assert parse_occurrence_filter("List orchids in Ecuador") is None
    assert parse_occurrence_filter("List orchids above 3000 meters") is None


def test_does_not_treat_binomial_as_country():
    assert parse_occurrence_filter("What is known about Laelia anceps above 2000 meters?") is None
