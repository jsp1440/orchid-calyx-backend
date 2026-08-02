from runtime.world_plants_ingest import WorldPlantsRow
from runtime.world_plants_synonyms import (
    parse_release_synonyms,
    parse_synonym_assertions,
)


def row(raw: str, name: str = "Accepted species") -> WorldPlantsRow:
    return WorldPlantsRow(
        source_row_number=12,
        values={"taxon_code": "S", "name": name, "synonyms_raw": raw},
    )


def test_multiple_assertions_and_citations_are_preserved():
    result = parse_synonym_assertions(
        row("= First synonym [Smith 1901] = Second synonym [Jones 2002]")
    )
    assert [item.synonym_name for item in result.assertions] == [
        "First synonym",
        "Second synonym",
    ]
    assert result.assertions[0].citation_fragment == "Smith 1901"
    assert result.raw_text.startswith("=")
    assert result.summary()["automatic_publication"] is False


def test_duplicate_assertions_are_flagged_and_not_duplicated():
    result = parse_synonym_assertions(row("= Same synonym = Same synonym"))
    assert len(result.assertions) == 1
    assert any(
        issue["reason"] == "duplicate_synonym_assertion" for issue in result.issues
    )


def test_self_synonym_is_flagged_for_review():
    result = parse_synonym_assertions(row("= Accepted species"))
    assert len(result.assertions) == 1
    assert any(issue["reason"] == "self_synonym" for issue in result.issues)
    assert result.assertions[0].requires_review is True


def test_blank_synonyms_produce_no_assertions():
    result = parse_synonym_assertions(row(""))
    assert result.assertions == ()
    assert result.issues == ()


def test_release_summary_is_fail_closed():
    result = parse_release_synonyms((row("= One"), row("", "Other accepted")))
    assert result["rows_with_synonyms"] == 1
    assert len(result["assertions"]) == 1
    assert result["manual_review_required"] is True
