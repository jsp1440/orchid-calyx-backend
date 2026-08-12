from __future__ import annotations

import pytest

from app.trait_genomics.molecular_review_queue import (
    MolecularReviewQueuePage,
    MolecularReviewQueueQuery,
    build_review_queue_filter,
)


def test_review_queue_defaults_are_bounded_and_review_neutral():
    query = MolecularReviewQueueQuery()
    where_sql, params = build_review_queue_filter(query)
    assert query.limit == 50
    assert query.offset == 0
    assert where_sql == "confidence_score >= %s"
    assert params == (0.0,)


def test_review_queue_filter_values_remain_parameters():
    query = MolecularReviewQueueQuery(
        review_state="candidate",
        evidence_kind="expression_association",
        canonical_taxon_id="oc:taxon:1",
        scientific_name="Dendrobium cuthbertsonii",
        source_id="pmid:123",
        min_confidence=0.55,
        limit=25,
        offset=50,
    )
    where_sql, params = build_review_queue_filter(query)
    assert "candidate" not in where_sql
    assert "Dendrobium cuthbertsonii" not in where_sql
    assert "pmid:123" not in where_sql
    assert where_sql.count("%s") == 6
    assert params == (
        0.55,
        "candidate",
        "expression_association",
        "oc:taxon:1",
        "%Dendrobium cuthbertsonii%",
        "pmid:123",
    )


def test_review_queue_rejects_unbounded_or_invalid_queries():
    with pytest.raises(ValueError):
        MolecularReviewQueueQuery(limit=201)
    with pytest.raises(ValueError):
        MolecularReviewQueueQuery(offset=-1)
    with pytest.raises(ValueError):
        MolecularReviewQueueQuery(min_confidence=1.1)
    with pytest.raises(ValueError):
        MolecularReviewQueueQuery(review_state="published")


def test_review_queue_page_marks_results_as_review_only():
    page = MolecularReviewQueuePage(
        total=1,
        limit=50,
        offset=0,
        items=({"association_id": "tig-mol:test", "review_state": "candidate"},),
    ).as_dict()
    assert page["review_required"] is True
    assert page["publication_enabled"] is False
    assert page["items"][0]["review_state"] == "candidate"
