from dataclasses import FrozenInstanceError

import pytest

from app.kernel import (
    OCIDFactory,
    QueryObjectType,
    QueryPage,
    QuerySort,
    QuerySortDirection,
    ScientificObjectValidationError,
    ScientificQuery,
)


def test_scientific_query_defaults_are_bounded() -> None:
    query = ScientificQuery()

    assert query.limit == 100
    assert query.offset == 0
    assert query.is_unfiltered


def test_scientific_query_is_immutable() -> None:
    query = ScientificQuery()

    with pytest.raises(FrozenInstanceError):
        query.limit = 10  # type: ignore[misc]


def test_scientific_query_normalizes_text_and_filters() -> None:
    query = ScientificQuery(text="  pollinator  ", filters={"region": "Peru"})

    assert query.text == "pollinator"
    assert query.filters["region"] == "Peru"
    with pytest.raises(TypeError):
        query.filters["region"] = "Ecuador"  # type: ignore[index]


def test_scientific_query_rejects_duplicate_selectors() -> None:
    object_ocid = OCIDFactory.new()

    with pytest.raises(ScientificObjectValidationError, match="ocids must be unique"):
        ScientificQuery(ocids=(object_ocid, object_ocid))


def test_scientific_query_rejects_invalid_pagination() -> None:
    with pytest.raises(ScientificObjectValidationError, match="between 1 and 1000"):
        ScientificQuery(limit=0)

    with pytest.raises(ScientificObjectValidationError, match="must not be negative"):
        ScientificQuery(offset=-1)


def test_scientific_query_supports_sorting_and_object_types() -> None:
    query = ScientificQuery(
        object_types=(QueryObjectType.ASSERTION, QueryObjectType.RELATIONSHIP),
        sort=(QuerySort("created_at", QuerySortDirection.DESCENDING),),
    )

    assert query.object_types == (
        QueryObjectType.ASSERTION,
        QueryObjectType.RELATIONSHIP,
    )
    assert query.sort[0].field_name == "created_at"
    assert query.sort[0].direction is QuerySortDirection.DESCENDING


def test_query_page_reports_remaining_results() -> None:
    page = QueryPage(items=("a", "b"), total=5, limit=2, offset=0)

    assert page.has_more


def test_query_page_rejects_total_smaller_than_items() -> None:
    with pytest.raises(ScientificObjectValidationError, match="smaller than item count"):
        QueryPage(items=("a", "b"), total=1)
