"""Tests for literature corpus discovery.

`/literature` shipped as a placeholder because papers could be fetched by id
and nothing could learn which ids existed. The frontend client was written
against a `list_papers` producer that had never landed.

Two distinctions carry the weight here, and both are things the page renders
differently:

* ``total`` is the corpus, not the page. Conflating them turns "no more
  results" into "no results".
* An unreadable extraction is returned with a reason, not skipped. Omitting it
  would report a smaller corpus than exists and hide the damage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.literature_extraction.repository import (
    LiteratureResultRepository,
    PaperSummary,
)
from app.literature_extraction.routes import (
    get_literature_repository,
)
from app.literature_extraction.routes import (
    router as literature_router,
)
from app.security import verify_owner_or_api_key


def paper_document(paper_id: str, *, claims: int = 0, evidence: int = 0) -> dict:
    """A minimal but schema-valid extraction bundle.

    Built against the real PaperKnowledge model rather than a convenient
    shape, so a test paper that the production reader would reject can never
    pass for a readable one here.
    """
    return {
        "schema_version": "1.0.0",
        "paper_id": paper_id,
        "source": {
            "content_hash": "0" * 32,
            "media_type": "text/plain",
            "original_filename": f"{paper_id}.txt",
        },
        "metadata": {
            "title": f"Paper {paper_id}",
            "authors": ["R\u00edos, M.", "Tan, L."],
            "journal": "Lindleyana",
            "publication_year": 2026,
        },
        "claims": [
            {
                "claim_id": f"c{n}",
                "statement": "a claim",
                "claim_type": "observation",
                "provenance": {"method": "rule_extracted", "confidence": 1.0},
            }
            for n in range(claims)
        ],
        "evidence": [
            {
                "evidence_id": f"e{n}",
                "excerpt": "a quote",
                "span": {"char_start": 0, "char_end": 6},
                "evidence_type": "text",
            }
            for n in range(evidence)
        ],
        "analysis_manifest": {
            "analysis_id": f"an-{paper_id}",
            "analysis_version": 1,
            "created_at": "2026-09-20T00:00:00+00:00",
            "pipeline_version": "1.0.0",
            "status": "completed",
        },
    }


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "literature"
    root.mkdir()
    return root


def write_paper(root: Path, paper_id: str, **kwargs) -> None:
    directory = root / paper_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "paper.json").write_text(
        json.dumps(paper_document(paper_id, **kwargs)), encoding="utf-8"
    )


def write_damaged_paper(root: Path, paper_id: str) -> None:
    directory = root / paper_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "paper.json").write_text("{ not valid json", encoding="utf-8")


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


def test_an_empty_corpus_lists_nothing(corpus: Path):
    repository = LiteratureResultRepository(corpus)
    assert repository.list_paper_ids() == []
    assert repository.count() == 0


def test_a_missing_root_is_empty_rather_than_an_error(tmp_path: Path):
    repository = LiteratureResultRepository(tmp_path / "never-created")
    assert repository.list_paper_ids() == []


def test_only_directories_holding_an_extraction_are_listed(corpus: Path):
    write_paper(corpus, "real")
    (corpus / "stray-file.txt").write_text("x", encoding="utf-8")
    (corpus / "empty-dir").mkdir()
    assert LiteratureResultRepository(corpus).list_paper_ids() == ["real"]


def test_listing_order_is_stable_so_paging_cannot_skip_a_paper(corpus: Path):
    for paper_id in ("c", "a", "b"):
        write_paper(corpus, paper_id)
    repository = LiteratureResultRepository(corpus)
    assert repository.list_paper_ids() == ["a", "b", "c"]
    assert repository.list_paper_ids() == repository.list_paper_ids()


def test_a_readable_paper_summarizes_identity_and_counts(corpus: Path):
    write_paper(corpus, "p1", claims=3, evidence=2)
    summary = LiteratureResultRepository(corpus).summarize("p1")
    assert summary.readable is True
    assert summary.title == "Paper p1"
    assert summary.authors == ("Ríos, M.", "Tan, L.")
    assert summary.journal == "Lindleyana"
    assert summary.publication_year == 2026
    assert summary.claim_count == 3
    assert summary.evidence_count == 2


def test_a_damaged_paper_is_reported_not_skipped(corpus: Path):
    write_damaged_paper(corpus, "broken")
    summary = LiteratureResultRepository(corpus).summarize("broken")
    assert summary.readable is False
    assert summary.reason


def test_an_absent_paper_reports_why(corpus: Path):
    summary = LiteratureResultRepository(corpus).summarize("nope")
    assert summary.readable is False
    assert summary.reason == "EXTRACTION_NOT_FOUND"


def test_a_summary_carries_no_section_text_or_claims():
    """A list response is identity and counts. Content has its own policies."""
    summary = PaperSummary(paper_id="p", readable=True, title="t", claim_count=9)
    payload = summary.as_dict()
    assert payload["claim_count"] == 9
    assert "claims" not in payload
    assert "sections" not in payload
    assert "evidence" not in payload


def test_an_unreadable_summary_exposes_only_identity_and_reason():
    payload = PaperSummary(paper_id="p", readable=False, reason="BROKEN").as_dict()
    assert payload == {"paper_id": "p", "readable": False, "reason": "BROKEN"}


def test_total_is_the_corpus_not_the_page(corpus: Path):
    for n in range(7):
        write_paper(corpus, f"p{n}")
    summaries, total = LiteratureResultRepository(corpus).list_summaries(
        limit=2, offset=0
    )
    assert len(summaries) == 2
    assert total == 7


def test_paging_walks_the_corpus_without_gaps_or_repeats(corpus: Path):
    for n in range(5):
        write_paper(corpus, f"p{n}")
    repository = LiteratureResultRepository(corpus)
    seen: list[str] = []
    for offset in (0, 2, 4):
        page, _ = repository.list_summaries(limit=2, offset=offset)
        seen.extend(s.paper_id for s in page)
    assert seen == ["p0", "p1", "p2", "p3", "p4"]
    assert len(set(seen)) == 5


def test_an_offset_past_the_end_is_an_empty_page_not_an_error(corpus: Path):
    write_paper(corpus, "only")
    page, total = LiteratureResultRepository(corpus).list_summaries(limit=10, offset=50)
    assert page == []
    assert total == 1


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@pytest.fixture
def client(corpus: Path) -> TestClient:
    app = FastAPI()
    app.include_router(literature_router)
    app.dependency_overrides[get_literature_repository] = lambda: (
        LiteratureResultRepository(corpus)
    )
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"owner": "test"}
    return TestClient(app)


def test_endpoint_returns_the_documented_envelope(client: TestClient, corpus: Path):
    write_paper(corpus, "p1", claims=2)
    body = client.get("/api/literature-extraction/papers").json()
    assert set(body) == {"papers", "total", "limit", "offset", "unreadable_count"}
    assert body["total"] == 1
    assert body["papers"][0]["paper_id"] == "p1"
    assert body["papers"][0]["claim_count"] == 2


def test_endpoint_returns_an_empty_corpus_as_a_valid_page(client: TestClient):
    response = client.get("/api/literature-extraction/papers")
    assert response.status_code == 200
    body = response.json()
    assert body["papers"] == []
    assert body["total"] == 0


def test_endpoint_keeps_damaged_rows_and_counts_them(client: TestClient, corpus: Path):
    write_paper(corpus, "good")
    write_damaged_paper(corpus, "bad")
    body = client.get("/api/literature-extraction/papers").json()
    assert body["total"] == 2
    assert len(body["papers"]) == 2
    assert body["unreadable_count"] == 1
    unreadable = [p for p in body["papers"] if p["readable"] is False]
    assert unreadable[0]["paper_id"] == "bad"
    assert unreadable[0]["reason"]


def test_endpoint_pages(client: TestClient, corpus: Path):
    for n in range(6):
        write_paper(corpus, f"p{n}")
    body = client.get("/api/literature-extraction/papers?limit=2&offset=2").json()
    assert [p["paper_id"] for p in body["papers"]] == ["p2", "p3"]
    assert body["total"] == 6
    assert body["limit"] == 2
    assert body["offset"] == 2


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=201", "limit=-1", "offset=-1", "limit=abc"]
)
def test_endpoint_rejects_out_of_range_paging(client: TestClient, query: str):
    """The client maps 422 to a distinct 'rejected' failure, so it must be 422."""
    assert client.get(f"/api/literature-extraction/papers?{query}").status_code == 422


def test_endpoint_accepts_the_documented_bounds(client: TestClient):
    assert client.get("/api/literature-extraction/papers?limit=200").status_code == 200
    assert client.get("/api/literature-extraction/papers?limit=1").status_code == 200


def test_listing_does_not_shadow_fetching_one_paper(client: TestClient, corpus: Path):
    """A collection route added beside an item route must not capture it."""
    write_paper(corpus, "p1")
    response = client.get("/api/literature-extraction/papers/p1")
    assert response.status_code == 200
    assert response.json()["paper_id"] == "p1"


def test_endpoint_is_owner_gated(corpus: Path):
    """Auth is enforced at the router, so discovery is not a public listing."""
    app = FastAPI()
    app.include_router(literature_router)
    app.dependency_overrides[get_literature_repository] = lambda: (
        LiteratureResultRepository(corpus)
    )
    response = TestClient(app).get("/api/literature-extraction/papers")
    assert response.status_code in (401, 403)
