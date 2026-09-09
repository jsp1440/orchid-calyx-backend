"""Regression tests for generalized external-literature query planning.

Gate 3 acceptance from issue #1187:
  At least five unrelated orchid taxa outside the current hard-coded genus list
  generate valid retrieval plans and review artifacts.

The five taxa from issue #1179 (Orchid-Continuum-Brain#101 mission):
  Calypso bulbosa, Pleione humilis, Ponerorchis graminifolia,
  Cephalanthera austiniae, Goodyera oblongifolia

All are outside the original 12-genus hardcoded list. These tests run offline
(no HTTP calls); they verify the query planner, not the network layer.
"""

from __future__ import annotations

import pytest

from app.calyx_conversation.external_literature import (
    _ORCHID_GENERA,
    _extract_potential_genera,
    _mentioned_genera,
    _query_plan,
)

# ---------------------------------------------------------------------------
# Known genera outside the hardcoded list (Gate 3 taxa)
# ---------------------------------------------------------------------------

GATE3_TAXA = [
    "Calypso bulbosa",
    "Pleione humilis",
    "Ponerorchis graminifolia",
    "Cephalanthera austiniae",
    "Goodyera oblongifolia",
]

GATE3_GENERA = [taxon.split()[0] for taxon in GATE3_TAXA]


def _none_in_hardcoded(genera: list[str]) -> bool:
    hardcoded_cf = {g.casefold() for g in _ORCHID_GENERA}
    return all(g.casefold() not in hardcoded_cf for g in genera)


def test_gate3_genera_are_not_in_hardcoded_list():
    assert _none_in_hardcoded(GATE3_GENERA), (
        "Gate 3 test invariant broken: some taxa are now in the hardcoded list"
    )


# ---------------------------------------------------------------------------
# _extract_potential_genera
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("taxon", GATE3_TAXA)
def test_extract_genus_from_binomial(taxon: str):
    genus = taxon.split()[0]
    found = _extract_potential_genera(taxon)
    assert genus in found, (
        f"Expected genus '{genus}' to be extracted from '{taxon}', got {found}"
    )


def test_extract_genera_from_sentence_with_binomials():
    text = "What do we know about Calypso bulbosa and Goodyera oblongifolia ecology?"
    found = _extract_potential_genera(text)
    assert "Calypso" in found
    assert "Goodyera" in found


def test_extract_does_not_include_stopwords():
    text = "The orchid family Orchidaceae grows in tropical regions"
    found = _extract_potential_genera(text)
    lower = [g.casefold() for g in found]
    assert "the" not in lower
    assert "orchid" not in lower
    assert "orchidaceae" not in lower
    assert "tropical" not in lower


# ---------------------------------------------------------------------------
# _mentioned_genera with text extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("taxon", GATE3_TAXA)
def test_mentioned_genera_detects_gate3_taxon_in_question(taxon: str):
    genus = taxon.split()[0]
    question = f"Tell me about {taxon} ecology and distribution"
    genera = _mentioned_genera(question)
    assert genus in genera, (
        f"Expected genus '{genus}' to be detected from question, got {genera}"
    )


def test_mentioned_genera_with_explicit_taxa_parameter():
    genera = _mentioned_genera("Tell me about orchid ecology", extra_taxa=GATE3_TAXA)
    for genus in GATE3_GENERA:
        assert genus in genera, f"Expected '{genus}' from extra_taxa, got {genera}"


def test_mentioned_genera_combines_hardcoded_and_extracted():
    question = "How does Calypso bulbosa compare to Laelia anceps?"
    genera = _mentioned_genera(question)
    assert "Calypso" in genera  # extracted from text
    assert "Laelia" in genera   # from hardcoded list


def test_mentioned_genera_no_duplicates():
    question = "Tell me about Calypso bulbosa distribution"
    genera = _mentioned_genera(question, extra_taxa=["Calypso bulbosa"])
    calypso_count = sum(1 for g in genera if g.casefold() == "calypso")
    assert calypso_count == 1, "Calypso should appear exactly once"


# ---------------------------------------------------------------------------
# _query_plan with Gate 3 taxa
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("taxon", GATE3_TAXA)
def test_query_plan_from_explicit_taxon(taxon: str):
    genus = taxon.split()[0]
    question = f"What is known about {taxon}?"
    queries = _query_plan(question, taxa=[taxon])
    assert len(queries) >= 1, f"Expected at least one query for {taxon}"
    assert any(genus in q for q in queries), (
        f"Expected '{genus}' to appear in at least one query, got {queries}"
    )


def test_query_plan_all_five_gate3_taxa():
    question = (
        "Provide evidence dossiers for Calypso bulbosa, Pleione humilis, "
        "Ponerorchis graminifolia, Cephalanthera austiniae, and Goodyera oblongifolia."
    )
    queries = _query_plan(question, taxa=GATE3_TAXA, max_queries=12)
    assert len(queries) >= 5, f"Expected at least 5 queries, got {len(queries)}: {queries}"
    covered = []
    for genus in GATE3_GENERA:
        if any(genus in q for q in queries):
            covered.append(genus)
    assert len(covered) >= 3, (
        f"Expected at least 3 Gate 3 genera in queries, covered: {covered}"
    )


def test_query_plan_deduplicated():
    question = "Tell me about Calypso bulbosa"
    queries = _query_plan(question, taxa=["Calypso bulbosa"], max_queries=8)
    lower_queries = [q.casefold().strip() for q in queries]
    assert len(lower_queries) == len(set(lower_queries)), "Duplicate queries found"


def test_query_plan_respects_max_queries():
    question = "Tell me about orchid ecology"
    queries = _query_plan(question, taxa=GATE3_TAXA, max_queries=5)
    assert len(queries) <= 5


def test_query_plan_explicit_taxa_without_question_context():
    # Question has no botanical content; taxa come only from explicit parameter
    queries = _query_plan("What do we know?", taxa=["Pleione humilis"], max_queries=4)
    assert any("Pleione" in q for q in queries), (
        f"Expected 'Pleione' in queries, got {queries}"
    )


# ---------------------------------------------------------------------------
# LiteratureAcquisitionService (runtime/literature_acquisition.py)
# ---------------------------------------------------------------------------


def test_literature_acquisition_service_import():
    from runtime.literature_acquisition import LiteratureAcquisitionService
    assert LiteratureAcquisitionService is not None


def test_literature_acquisition_run_dir_valid(tmp_path):
    from runtime.literature_acquisition import LiteratureAcquisitionService
    svc = LiteratureAcquisitionService(tmp_path)
    run_dir = svc._run_dir("run-001")
    assert run_dir == tmp_path / "runs" / "run-001"


def test_literature_acquisition_run_dir_invalid(tmp_path):
    from runtime.literature_acquisition import LiteratureAcquisitionService
    svc = LiteratureAcquisitionService(tmp_path)
    with pytest.raises(ValueError, match="LITERATURE_RUN_ID_INVALID"):
        svc._run_dir("../evil")


def test_literature_acquisition_readiness_unavailable(tmp_path):
    from runtime.literature_acquisition import LiteratureAcquisitionService
    svc = LiteratureAcquisitionService(tmp_path)
    result = svc.readiness("nonexistent-run")
    assert result["status"] == "UNAVAILABLE"
    assert result["ready_for_review"] is False
    assert result["evidence_span_count"] == 0


def test_literature_acquisition_readiness_available(tmp_path):
    import json

    from runtime.literature_acquisition import LiteratureAcquisitionService
    svc = LiteratureAcquisitionService(tmp_path)
    run_dir = svc._run_dir("run-test-001")
    run_dir.mkdir(parents=True)
    readiness = {
        "status": "READY",
        "source_sha256": "abc123",
        "extraction_sha256": "def456",
        "evidence_span_count": 42,
        "ready_for_review": True,
    }
    (run_dir / "readiness.json").write_text(json.dumps(readiness))
    result = svc.readiness("run-test-001")
    assert result["status"] == "READY"
    assert result["source_sha256"] == "abc123"
    assert result["evidence_span_count"] == 42
    assert result["ready_for_review"] is True


def test_literature_acquisition_list_runs(tmp_path):
    from runtime.literature_acquisition import LiteratureAcquisitionService
    svc = LiteratureAcquisitionService(tmp_path)
    (tmp_path / "runs" / "run-a").mkdir(parents=True)
    (tmp_path / "runs" / "run-b").mkdir(parents=True)
    runs = svc.list_runs()
    assert "run-a" in runs
    assert "run-b" in runs


def test_literature_acquisition_status(tmp_path):
    from runtime.literature_acquisition import LiteratureAcquisitionService
    svc = LiteratureAcquisitionService(tmp_path)
    status = svc.status()
    assert status["root"] == str(tmp_path)
    assert "run_count" in status
