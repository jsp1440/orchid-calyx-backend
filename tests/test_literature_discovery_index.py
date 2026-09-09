"""Discovery for the literature extraction store.

The module could return a paper by id and offered no way to learn which ids
exist. So nothing could build an index without inventing one, and `/literature`
shipped as a placeholder while real extractions sat in the store.

Two properties carry the weight here.

An **unreadable record is reported, not skipped.** A directory with no
`paper.json` is an incomplete write; omitting it silently would make the corpus
look smaller than it is, and a caller comparing `len(papers)` to `total` would
see an unexplained gap.

**Summaries carry identity and counts, never bodies.** Section text, claims and
evidence have their own display policies, and a list endpoint is the wrong
place to adjudicate them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.routes import list_papers


def write_paper(root: Path, paper_id: str, **overrides) -> None:
    directory = root / paper_id
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "1.0.0",
        "paper_id": paper_id,
        "metadata": {
            "title": f"Thermal niche in {paper_id}",
            "authors": ["A. Botanist", "B. Ecologist"],
            "journal": "Orchid Science",
            "publication_year": 2026,
            "abstract": "A long abstract that must not appear in a summary.",
        },
        "sections": [{"text": "Body text that must not appear in a summary."}],
        "claims": [{"id": "c1"}, {"id": "c2"}],
        "evidence": [{"id": "e1"}],
        "review_decisions": [],
    }
    record.update(overrides)
    (directory / "paper.json").write_text(json.dumps(record), encoding="utf-8")


@pytest.fixture()
def store(tmp_path: Path) -> LiteratureResultRepository:
    return LiteratureResultRepository(tmp_path)


def test_lists_the_papers_that_exist(store, tmp_path):
    write_paper(tmp_path, "paper-a")
    write_paper(tmp_path, "paper-b")

    summaries, total = store.list_summaries()

    assert total == 2
    assert [item["paper_id"] for item in summaries] == ["paper-a", "paper-b"]
    assert all(item["readable"] for item in summaries)


def test_summaries_carry_identity_and_counts_not_bodies(store, tmp_path):
    write_paper(tmp_path, "paper-a")

    summary = store.list_summaries()[0][0]

    assert summary["title"] == "Thermal niche in paper-a"
    assert summary["claim_count"] == 2
    assert summary["evidence_count"] == 1
    # The boundary: nothing releasable-by-policy is in a list response.
    serialized = json.dumps(summary)
    assert "Body text" not in serialized
    assert "long abstract" not in serialized
    assert "sections" not in summary
    assert "abstract" not in summary


def test_an_incomplete_write_is_reported_not_skipped(store, tmp_path):
    write_paper(tmp_path, "paper-a")
    (tmp_path / "paper-broken").mkdir()  # directory with no paper.json

    summaries, total = store.list_summaries()

    assert total == 2
    broken = next(item for item in summaries if item["paper_id"] == "paper-broken")
    assert broken["readable"] is False
    assert broken["reason"] == "PAPER_RECORD_MISSING"


def test_an_unparseable_record_is_reported_not_skipped(store, tmp_path):
    write_paper(tmp_path, "paper-a")
    broken = tmp_path / "paper-corrupt"
    broken.mkdir()
    (broken / "paper.json").write_text("{ not json", encoding="utf-8")

    summaries, _ = store.list_summaries()

    corrupt = next(item for item in summaries if item["paper_id"] == "paper-corrupt")
    assert corrupt["readable"] is False
    assert corrupt["reason"] == "PAPER_RECORD_UNREADABLE"


def test_an_absent_store_is_zero_not_an_error(store, tmp_path):
    # A store that has not been written yet is not a corpus of zero papers, but
    # it is also not a failure. Zero with a zero total lets the caller tell it
    # from a page past the end.
    missing = LiteratureResultRepository(tmp_path / "does-not-exist")
    assert missing.list_summaries() == ([], 0)


def test_paging_is_stable_and_bounded(store, tmp_path):
    for index in range(5):
        write_paper(tmp_path, f"paper-{index}")

    first, total = store.list_summaries(limit=2, offset=0)
    second, _ = store.list_summaries(limit=2, offset=2)

    assert total == 5
    assert [item["paper_id"] for item in first] == ["paper-0", "paper-1"]
    assert [item["paper_id"] for item in second] == ["paper-2", "paper-3"]
    # Sorted, so a second call returns the same page rather than whatever the
    # filesystem happened to enumerate.
    assert store.list_summaries(limit=2, offset=0)[0] == first


def test_an_oversized_limit_is_clamped(store, tmp_path):
    for index in range(3):
        write_paper(tmp_path, f"paper-{index}")

    summaries, _ = store.list_summaries(limit=100_000)

    assert len(summaries) == 3  # clamped to 200, then to what exists


def test_an_offset_past_the_end_is_empty_but_reports_the_total(store, tmp_path):
    write_paper(tmp_path, "paper-a")

    summaries, total = store.list_summaries(offset=50)

    assert summaries == []
    # "No more results" stays distinct from "no results".
    assert total == 1


def test_authors_are_bounded(store, tmp_path):
    write_paper(
        tmp_path,
        "paper-many",
        metadata={"title": "Many authors", "authors": [f"Author {i}" for i in range(40)]},
    )

    summary = store.list_summaries()[0][0]

    assert len(summary["authors"]) == 10


class FakeRepository:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def list_summaries(self, *, limit, offset):
        self.calls.append((limit, offset))
        return self.result


def test_the_route_reports_the_page_the_total_and_the_unreadable_count():
    repository = FakeRepository(
        (
            [
                {"paper_id": "a", "readable": True, "claim_count": 1},
                {"paper_id": "b", "readable": False, "reason": "PAPER_RECORD_MISSING"},
            ],
            7,
        )
    )

    body = list_papers(repository, limit=2, offset=0)

    assert body["total"] == 7
    assert body["limit"] == 2
    assert body["offset"] == 0
    # Surfaced so a caller never has to scan the page to notice the corpus has
    # damaged records.
    assert body["unreadable_count"] == 1


@pytest.mark.parametrize("limit,offset", [(0, 0), (-1, 0), (10, -1)])
def test_the_route_rejects_invalid_page_bounds(limit, offset):
    repository = FakeRepository(([], 0))

    with pytest.raises(HTTPException) as excinfo:
        list_papers(repository, limit=limit, offset=offset)

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "INVALID_PAGE_BOUNDS"
    # It failed before touching the store.
    assert repository.calls == []


def test_an_empty_corpus_is_an_empty_page_not_an_error():
    repository = FakeRepository(([], 0))

    body = list_papers(repository, limit=10, offset=0)

    assert body["papers"] == []
    assert body["total"] == 0
    assert body["unreadable_count"] == 0
