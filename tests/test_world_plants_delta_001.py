from runtime.world_plants_delta import compare_and_crosswalk
from runtime.world_plants_ingest import WorldPlantsRow


def row(number: int, code: str, wp_number: str, name: str) -> WorldPlantsRow:
    values = {
        "taxon_code": code,
        "world_plants_number": wp_number,
        "name": name,
    }
    return WorldPlantsRow(source_row_number=number, values=values)


def test_exact_name_and_rank_is_automatically_accepted():
    result = compare_and_crosswalk(
        [row(2, "S", "", "Cattleya testensis Author")],
        [row(2, "S", "", "Cattleya testensis Author")],
    )
    candidate = result.candidates[0]
    assert candidate.classification == "unchanged"
    assert candidate.automatic_acceptance is True
    assert result.promotion_blocked is False


def test_world_plants_number_supports_authority_exact_name_change():
    result = compare_and_crosswalk(
        [row(2, "S", "123", "Oldgenus testensis Author")],
        [row(8, "S", "123", "Newgenus testensis Author")],
    )
    candidate = result.candidates[0]
    assert candidate.classification == "genus_transfer"
    assert candidate.confidence == "authority_exact"
    assert candidate.automatic_acceptance is False
    assert result.promotion_blocked is False


def test_duplicate_number_is_ambiguous_and_blocks():
    result = compare_and_crosswalk(
        [row(2, "S", "123", "Oldgenus testensis")],
        [
            row(8, "S", "123", "Newgenus testensis"),
            row(9, "S", "123", "Othergenus testensis"),
        ],
    )
    assert result.candidates[0].classification == "ambiguous"
    assert result.promotion_blocked is True
    assert result.as_dict()["fuzzy_matching_used"] is False


def test_removed_and_added_rows_are_reported():
    result = compare_and_crosswalk(
        [row(2, "S", "", "Missing species")],
        [row(7, "S", "", "New species")],
    )
    assert result.summary["removed"] == 1
    assert result.summary["added"] == 1
    assert result.added_rows == (7,)
    assert result.promotion_blocked is True


def test_rank_change_from_stable_number_requires_review():
    result = compare_and_crosswalk(
        [row(2, "S", "123", "Test taxon")],
        [row(3, "V", "123", "Test taxon")],
    )
    candidate = result.candidates[0]
    assert candidate.classification == "rank_change"
    assert candidate.automatic_acceptance is False
