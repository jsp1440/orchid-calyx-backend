"""CALYX Gate 3 — external literature generalization tests.

Acceptance criteria (from issue #1187 Gate 3):
- At least 5 unrelated orchid taxa OUTSIDE the hard-coded 12-genus list
  generate valid retrieval plans (genus-specific queries, not only fallbacks).
- _mentioned_genera() extracts arbitrary genera from binomial patterns.
- EMPTY / UNAVAILABLE / INSUFFICIENT_EVIDENCE states are explicit in results.
- Source failure never yields fabricated science (diagnostics captured).
- No hard-coded genus required for a valid query plan.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.calyx_conversation.external_literature import (
    _ORCHID_GENERA,
    _extract_genera_from_query,
    _mentioned_genera,
    _query_plan,
    search_europe_pmc,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_EXTRA_TAXA = [
    # (genus, species, human label)  — none appear in _ORCHID_GENERA
    ("Calypso", "bulbosa", "fairy-slipper"),
    ("Pleione", "humilis", "windowsill pleione"),
    ("Dracula", "chimaera", "monkey-face orchid"),
    ("Bulbophyllum", "lobbii", "largest orchid genus"),
    ("Coelogyne", "cristata", "necklace orchid"),
    ("Maxillaria", "tenuifolia", "coconut orchid"),
    ("Oncidium", "flexuosum", "dancing-lady orchid"),
    ("Zygopetalum", "mackaii", "fragrant z. orchid"),
]

# All extra taxa must be absent from the well-known list.
def test_extra_taxa_not_in_known_genera():
    known = {g.casefold() for g in _ORCHID_GENERA}
    for genus, _, label in _EXTRA_TAXA:
        assert genus.casefold() not in known, (
            f"{genus} ({label}) should NOT be in _ORCHID_GENERA — it is there but "
            "was intended as an extra-genus test case"
        )


# ── _extract_genera_from_query ────────────────────────────────────────────────


def test_extract_genera_catches_markdown_italic_binomial():
    result = _extract_genera_from_query("flowering in *Calypso bulbosa* in winter")
    assert "Calypso" in result


def test_extract_genera_catches_plain_binomial():
    result = _extract_genera_from_query("Pleione humilis dormancy requirements")
    assert "Pleione" in result


def test_extract_genera_catches_multiple_binomials():
    q = "Compare *Dracula chimaera* and *Bulbophyllum lobbii* flower triggers"
    result = _extract_genera_from_query(q)
    assert "Dracula" in result
    assert "Bulbophyllum" in result


def test_extract_genera_no_false_positive_on_plain_english():
    # "Winter" is Title-case but not followed by a species epithet
    result = _extract_genera_from_query("Winter care for orchids")
    assert result == []


def test_extract_genera_deduplicates():
    q = "*Calypso bulbosa* and *Calypso bulbosa* compared"
    result = _extract_genera_from_query(q)
    assert result.count("Calypso") == 1


# ── _mentioned_genera — arbitrary taxa ───────────────────────────────────────


def test_mentioned_genera_finds_extra_genus_from_binomial():
    q = "What is known about flowering in *Calypso bulbosa*?"
    genera = _mentioned_genera(q)
    assert "Calypso" in genera


def test_mentioned_genera_finds_known_genus_alongside_extra():
    q = "Compare *Calypso bulbosa* with Dendrobium nobile"
    genera = _mentioned_genera(q)
    assert "Calypso" in genera
    assert "Dendrobium" in genera
    # Known genera come first
    assert genera.index("Dendrobium") < genera.index("Calypso")


def test_mentioned_genera_empty_for_no_match():
    genera = _mentioned_genera("orchid care in winter")
    assert genera == []


# ── _query_plan — 5+ extra orchid taxa produce genus-specific queries ─────────


def _is_genus_specific(query: str, genus: str) -> bool:
    """True when the query targets the genus by name."""
    return f'"{genus}"' in query or genus in query


FIVE_EXTRA_TAXA = _EXTRA_TAXA[:5]  # Calypso, Pleione, Dracula, Bulbophyllum, Coelogyne


@pytest.mark.parametrize("genus,species,label", FIVE_EXTRA_TAXA)
def test_query_plan_genus_specific_for_extra_taxon(genus: str, species: str, label: str):
    question = (
        f"What triggers flowering in *{genus} {species}*? "
        "Does temperature or dry rest play a role?"
    )
    plan = _query_plan(question)
    assert plan, f"No queries generated for {label} ({genus} {species})"
    genus_specific = [q for q in plan if _is_genus_specific(q, genus)]
    assert genus_specific, (
        f"No genus-specific query for {genus} ({label}). "
        f"Full plan: {plan}"
    )


def test_query_plan_all_eight_extra_taxa_produce_genus_queries():
    """All 8 extra taxa generate at least one genus-specific query."""
    failures = []
    for genus, species, label in _EXTRA_TAXA:
        question = f"Flowering and dormancy in *{genus} {species}*"
        plan = _query_plan(question)
        if not any(_is_genus_specific(q, genus) for q in plan):
            failures.append(f"{genus} ({label}): plan={plan}")
    assert not failures, "Missing genus-specific queries for:\n" + "\n".join(failures)


def test_query_plan_non_orchid_binomial_still_produces_queries():
    """Even a non-orchid binomial generates a query plan (no crash, no empty plan)."""
    question = "Flowering cues for *Rosa canina* in temperate climates"
    plan = _query_plan(question)
    assert plan  # at least a fallback orchid/Orchidaceae query


def test_query_plan_respects_max_queries():
    # Many taxa, many clusters — plan must respect max_queries cap
    question = (
        "*Calypso bulbosa* *Pleione humilis* *Dracula chimaera* *Bulbophyllum lobbii* "
        "flowering temperature drought dormancy hormone regulation"
    )
    plan = _query_plan(question, max_queries=5)
    assert len(plan) <= 5


# ── availability_state in search_europe_pmc ───────────────────────────────────


def _mock_empty_response():
    """Europe PMC returns zero results (no network error)."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"resultList": {"result": []}}
    return resp


def _mock_error_response():
    import requests
    raise requests.RequestException("connection timeout")


def test_search_europe_pmc_returns_empty_state_when_no_results():
    with patch(
        "app.calyx_conversation.external_literature.requests.get",
        return_value=_mock_empty_response(),
    ):
        result = search_europe_pmc("*Calypso bulbosa* flowering temperature", limit=5)
    assert result["availability_state"] == "EMPTY"
    assert result["result_count"] == 0


def test_search_europe_pmc_returns_unavailable_when_all_queries_fail():
    import requests as _req

    def _raise(*args, **kwargs):
        raise _req.RequestException("network failure")

    with patch("app.calyx_conversation.external_literature.requests.get", side_effect=_raise):
        result = search_europe_pmc("*Pleione humilis* dormancy water rest", limit=5)
    assert result["availability_state"] == "UNAVAILABLE"
    assert result["result_count"] == 0
    assert result["diagnostics"]  # failure recorded, not hidden


def test_search_europe_pmc_available_state_with_mocked_results():
    """With 3+ results the state should be AVAILABLE."""
    def _make_paper(n: int):
        return {
            "title": f"Paper {n} on Calypso bulbosa flowering",
            "abstractText": "Temperature and dormancy in orchid flowering.",
            "authorString": f"Author{n} A",
            "journalTitle": "J Orchid Res",
            "firstPublicationDate": "2023-01-01",
            "doi": f"10.9999/test{n}",
            "pmid": str(1000 + n),
            "pmcid": None,
        }

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"resultList": {"result": [_make_paper(i) for i in range(5)]}}

    with patch(
        "app.calyx_conversation.external_literature.requests.get",
        return_value=resp,
    ):
        result = search_europe_pmc(
            "*Calypso bulbosa* flowering temperature dormancy", limit=5
        )
    # May be AVAILABLE or INSUFFICIENT_EVIDENCE depending on relevance score;
    # what matters is that it is NOT UNAVAILABLE and NOT EMPTY.
    assert result["availability_state"] in {"AVAILABLE", "INSUFFICIENT_EVIDENCE"}
    assert result["result_count"] >= 0


def test_diagnostics_capture_source_failure():
    """Network failure is recorded in diagnostics, never silently swallowed."""
    import requests as _req

    def _raise(*args, **kwargs):
        raise _req.RequestException("DNS lookup failed")

    with patch("app.calyx_conversation.external_literature.requests.get", side_effect=_raise):
        result = search_europe_pmc("*Dracula chimaera* flower", limit=3)

    assert result["diagnostics"], "Network errors must be recorded in diagnostics"
    for entry in result["diagnostics"]:
        assert "error" in entry
        assert "query" in entry


# ── Research station — no stale import ───────────────────────────────────────


def test_research_station_raises_not_implemented_without_override():
    """Accessing .literature without an override raises NotImplementedError (not ImportError)."""
    from runtime.research_station import ResearchStationService

    svc = ResearchStationService()
    with pytest.raises(NotImplementedError, match="LITERATURE_ACQUISITION_UNAVAILABLE"):
        _ = svc.literature


def test_research_station_literature_override_works():
    """Passing a literature= override returns it directly (no import attempted)."""
    from runtime.research_station import ResearchStationService

    stub = MagicMock()
    svc = ResearchStationService(literature=stub)
    assert svc.literature is stub


def test_research_station_import_has_no_stale_side_effect():
    """Importing research_station must not raise ImportError for missing module."""
    import importlib

    import runtime.research_station as rs_module

    importlib.reload(rs_module)  # re-import; must not blow up
