"""Tests for app.calyx_conversation.knowledge_context — KALIX-CONTEXT-001.

Six required behavioral axes:
  1. Lexicon context reaches Calyx (mock loader)
  2. Literature context reaches Calyx (mock repository)
  3. Provenance survives the bridge intact
  4. Empty / unavailable sources fail gracefully (available=False, no raise)
  5. Unrelated context is not injected (off-topic query → 0 matches)
  6. Existing Calyx compatible — governed_context dict shape is preserved
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.calyx_conversation.knowledge_context import (
    _query_terms,
    _term_overlap,
    build_knowledge_context,
    build_lexicon_context,
    build_literature_context,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_provenance(**kw: Any) -> Any:
    p = MagicMock()
    p.method = kw.get("method", "rule_extracted")
    p.confidence = kw.get("confidence", 0.9)
    p.review_status = kw.get("review_status", "accepted")
    p.extractor = kw.get("extractor", "test-extractor")
    return p


def _make_claim(cid: str, statement: str, *, review_status: str = "accepted") -> Any:
    c = MagicMock()
    c.claim_id = cid
    c.statement = statement
    c.claim_type = "observation"
    c.polarity = "positive"
    c.provenance = _make_provenance(review_status=review_status)
    return c


def _make_paper(paper_id: str, title: str, claims: list[Any] | None = None) -> Any:
    paper = MagicMock()
    paper.paper_id = paper_id
    meta = MagicMock()
    meta.title = title
    meta.abstract = f"Abstract about {title}"
    meta.keywords = []
    meta.identifiers = []
    paper.metadata = meta
    paper.claims = claims or []
    paper.entities = []
    manifest = MagicMock()
    manifest.status = "completed"
    paper.analysis_manifest = manifest
    return paper


def _mock_loader(entries: list[dict[str, Any]]) -> Any:
    def loader(*, q: str, limit: int) -> list[dict[str, Any]]:
        return entries

    return loader


def _mock_repository(papers: dict[str, Any]) -> Any:
    repo = MagicMock()
    repo.list_paper_ids.return_value = sorted(papers)
    def get(paper_id: str) -> Any:
        return papers.get(paper_id)
    repo.get.side_effect = get
    return repo


ORCHID_ENTRY: dict[str, Any] = {
    "preferred_term": "Dendrobium",
    "quick_definition": "A large genus of orchid found throughout Asia and Australasia.",
    "expanded_definition": "Dendrobium comprises over 1800 accepted species.",
    "synonyms": ["Den."],
    "maturity": ["established"],
    "provenance": {
        "source": "Orchid Continuum Core Concept Registry",
        "validation_status": "APPROVED",
    },
    "review_state": "APPROVED",
}


# ── 1. Lexicon context reaches Calyx ──────────────────────────────────────────

def test_lexicon_context_returns_matched_terms() -> None:
    loader = _mock_loader([ORCHID_ENTRY])
    ctx = build_lexicon_context("Tell me about Dendrobium orchids", loader=loader)
    assert ctx["available"] is True
    assert ctx["matched_terms"] == 1
    assert ctx["terms"][0]["preferred_term"] == "Dendrobium"


def test_lexicon_context_schema_field_present() -> None:
    loader = _mock_loader([ORCHID_ENTRY])
    ctx = build_lexicon_context("Dendrobium culture tips", loader=loader)
    assert ctx["schema"] == "oc.calyx-knowledge-context.v1"
    assert ctx["source"] == "oc_lexicon"


def test_lexicon_context_included_in_knowledge_context() -> None:
    loader = _mock_loader([ORCHID_ENTRY])
    ctx = build_knowledge_context(
        "Dendrobium culture tips",
        include_literature=False,
        lexicon_loader=loader,
    )
    assert ctx["lexicon"]["available"] is True
    assert ctx["lexicon"]["matched_terms"] == 1


# ── 2. Literature context reaches Calyx ───────────────────────────────────────

def test_literature_context_returns_matched_papers() -> None:
    claim = _make_claim("c1", "Cattleya grows in bright light.")
    paper = _make_paper("paper-001", "Cattleya culture study", claims=[claim])
    repo = _mock_repository({"paper-001": paper})

    ctx = build_literature_context("Cattleya bright light", repository=repo)
    assert ctx["available"] is True
    assert ctx["matched_papers"] == 1
    assert ctx["papers"][0]["citation"]["title"] == "Cattleya culture study"


def test_literature_context_included_in_knowledge_context() -> None:
    claim = _make_claim("c2", "Orchid roots absorb humidity.", review_status="accepted")
    paper = _make_paper("paper-abc", "Root biology of epiphytes", claims=[claim])
    repo = _mock_repository({"paper-abc": paper})

    ctx = build_knowledge_context(
        "orchid root humidity",
        include_lexicon=False,
        literature_repository=repo,
    )
    assert ctx["literature"]["available"] is True
    assert ctx["literature"]["matched_papers"] == 1


# ── 3. Provenance survives the bridge intact ──────────────────────────────────

def test_lexicon_provenance_preserved() -> None:
    loader = _mock_loader([ORCHID_ENTRY])
    ctx = build_lexicon_context("Dendrobium", loader=loader)
    prov = ctx["terms"][0]["provenance"]
    assert prov["source"] == "Orchid Continuum Core Concept Registry"
    assert prov["validation_status"] == "APPROVED"


def test_literature_claim_provenance_preserved() -> None:
    claim = _make_claim("c3", "Phalaenopsis prefers low light.")
    paper = _make_paper("p1", "Moth orchid guide", claims=[claim])
    repo = _mock_repository({"p1": paper})

    ctx = build_literature_context("Phalaenopsis light", repository=repo)
    claim_out = ctx["papers"][0]["claims"][0]
    prov_out = claim_out["provenance"]
    assert prov_out["method"] == "rule_extracted"
    assert prov_out["confidence"] == pytest.approx(0.9)
    assert prov_out["review_status"] == "accepted"
    assert prov_out["extractor"] == "test-extractor"


def test_rejected_claims_excluded() -> None:
    accepted = _make_claim("ca", "Good claim.", review_status="accepted")
    rejected = _make_claim("cr", "Rejected claim.", review_status="rejected")
    paper = _make_paper("p2", "Test paper", claims=[accepted, rejected])
    repo = _mock_repository({"p2": paper})

    ctx = build_literature_context("test query", repository=repo)
    ids = [c["claim_id"] for c in ctx["papers"][0]["claims"]]
    assert "ca" in ids
    assert "cr" not in ids


# ── 4. Empty / unavailable sources fail gracefully ───────────────────────────

def test_empty_lexicon_returns_available_false() -> None:
    ctx = build_lexicon_context("Dendrobium", loader=_mock_loader([]))
    assert ctx["available"] is False
    assert ctx["matched_terms"] == 0
    assert ctx["terms"] == []


def test_lexicon_db_failure_does_not_raise() -> None:
    def failing_loader(**_kw: Any) -> list[Any]:
        raise RuntimeError("DB connection refused")

    ctx = build_lexicon_context("Dendrobium", loader=failing_loader)
    assert ctx["available"] is False


def test_literature_empty_repository_returns_available_false() -> None:
    repo = _mock_repository({})
    ctx = build_literature_context("Dendrobium", repository=repo)
    assert ctx["available"] is False
    assert ctx["matched_papers"] == 0


def test_combined_lexicon_failure_does_not_affect_literature() -> None:
    paper = _make_paper("p3", "Vanilla planifolia study")
    repo = _mock_repository({"p3": paper})

    def boom(**_kw: Any) -> list[Any]:
        raise RuntimeError("Lexicon exploded")

    ctx = build_knowledge_context(
        "Vanilla planifolia",
        lexicon_loader=boom,
        literature_repository=repo,
    )
    assert ctx["lexicon"]["available"] is False
    assert ctx["literature"]["available"] is True


def test_combined_literature_failure_does_not_affect_lexicon() -> None:
    loader = _mock_loader([ORCHID_ENTRY])

    repo = _mock_repository({})

    ctx = build_knowledge_context(
        "Dendrobium culture",
        lexicon_loader=loader,
        literature_repository=repo,
    )
    assert ctx["lexicon"]["available"] is True
    assert ctx["literature"]["available"] is False


# ── 5. No indiscriminate injection — unrelated query → 0 matches ─────────────

def test_unrelated_query_yields_no_lexicon_hits() -> None:
    generic_entry = {
        "preferred_term": "Phalaenopsis",
        "quick_definition": "Moth orchid genus.",
        "expanded_definition": "Widely grown epiphytic orchid.",
        "synonyms": [],
        "maturity": ["established"],
        "provenance": {"source": "OC Registry", "validation_status": "APPROVED"},
        "review_state": "APPROVED",
    }
    loader = _mock_loader([generic_entry])
    ctx = build_lexicon_context("the weather is nice today", loader=loader)
    assert ctx["matched_terms"] == 0


def test_query_terms_extracts_scientific_words() -> None:
    terms = _query_terms("What is the best light for Phalaenopsis culture?")
    assert "Phalaenopsis" in terms
    assert "culture" in terms
    assert "the" not in terms
    assert "for" not in terms


def test_term_overlap_counts_correctly() -> None:
    assert _term_overlap("Dendrobium culture in tropical Asia", ["Dendrobium", "tropical"]) == 2
    assert _term_overlap("nothing matches here", ["Phalaenopsis", "culture"]) == 0


# ── 6. Existing Calyx compatibility ──────────────────────────────────────────

def test_knowledge_context_governance_fields() -> None:
    ctx = build_knowledge_context("Orchid care", include_lexicon=False, include_literature=False)
    assert ctx["read_only"] is True
    assert ctx["canonical_graph_mutated"] is False
    assert ctx["engineering_dispatch_authorized"] is False
    assert ctx["provider_calls"] == 0


def test_knowledge_context_schema_version() -> None:
    ctx = build_knowledge_context("test", include_lexicon=False, include_literature=False)
    assert ctx["schema"] == "oc.calyx-knowledge-context.v1"


def test_knowledge_context_dict_is_json_serialisable() -> None:
    import json
    loader = _mock_loader([ORCHID_ENTRY])
    ctx = build_knowledge_context("Dendrobium", include_literature=False, lexicon_loader=loader)
    # Must not raise
    encoded = json.dumps(ctx)
    decoded = json.loads(encoded)
    assert decoded["schema"] == "oc.calyx-knowledge-context.v1"


def test_literature_uses_repository_paper_id_interface() -> None:
    paper = _make_paper("paper-1", "Repository abstraction")
    repo = _mock_repository({"paper-1": paper})

    ctx = build_literature_context("Repository abstraction", repository=repo)

    repo.list_paper_ids.assert_called_once_with()
    assert ctx["matched_papers"] == 1


def test_literature_repository_listing_failure_fails_gracefully() -> None:
    repo = MagicMock()
    repo.list_paper_ids.side_effect = RuntimeError("storage unavailable")

    ctx = build_literature_context("Dendrobium", repository=repo)

    assert ctx["available"] is False
    assert ctx["matched_papers"] == 0
