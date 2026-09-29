"""Focused orchestration contracts; PostgreSQL proof lives in test_firecrawl_postgres."""

import pytest

from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService
from app.literature_extraction.candidate_handoff import (
    LiteratureCandidateHandoffService,
)
from app.literature_extraction.firecrawl_acquisition import (
    acquire_matrix_sources,
    held_source_match,
)
from app.literature_extraction.firecrawl_provider import (
    AcquiredSource,
    AcquisitionBlocked,
    FirecrawlConfig,
    FirecrawlProvider,
)
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.source_binding import CanonicalLiteratureSourceBinding
from tests.test_firecrawl_matrix_acquisition import CONFIG, TEXT, URL, taxonomy, transport


def services(tmp_path):
    candidates = MemoryCandidateRepository()

    def bind(source, paper):
        return CanonicalLiteratureSourceBinding(
            paper.paper_id,
            "LITERATURE_DOCUMENT",
            1,
            2,
            3,
            {e.evidence_id: index for index, e in enumerate(paper.evidence, 1)},
        ).with_verified_integrity(paper, source.markdown.encode())

    return {
        "genus": "Paphiopedilum",
        "task_id": "fixture",
        "taxonomy": taxonomy(),
        "literature_repository": LiteratureResultRepository(tmp_path),
        "register_and_bind": bind,
        "handoff_service": LiteratureCandidateHandoffService(
            CandidateExtractionService(candidates), candidates
        ),
        "aggregation_service": EvidenceAggregationService(MemoryAggregateRepository()),
        "verify_lease": lambda: None,
    }


@pytest.mark.asyncio
async def test_sufficient_held_corpus_uses_zero_provider_calls(tmp_path):
    provider = FirecrawlProvider(
        FirecrawlConfig()
    )  # disabled/no key is fine for held-source reuse
    source = AcquiredSource(URL, TEXT, True)
    result = await acquire_matrix_sources(
        **services(tmp_path),
        provider=provider,
        corpus_audit=lambda: {
            "available": True,
            "complete": True,
            "documents": [{"loadable": True}],
            "identities": [{"content_hash": source.content_hash}],
        },
        load_held_source=lambda document: source,
        target_names=("Paphiopedilum delenatii",),
        required_predicates=("leaf_length",),
    )
    assert provider.calls == provider.credits_reserved == 0
    assert result["corpus_metrics"]["existing_documents_reused"] == 1
    assert result["corpus_metrics"]["remaining_gaps"] == []
    assert result["corpus_decision"] == "EXISTING_CORPUS_SUFFICIENT"
    assert result["coverage_scope"]["full_matrix_coverage"] is False
    metrics = result["corpus_metrics"]
    assert metrics["existing_sources_checked"] == metrics["existing_sources_used"] == 1
    assert metrics["existing_documents_reprocessed"] == 1
    assert (
        metrics["firecrawl_searches"]
        == metrics["firecrawl_pages"]
        == metrics["credits_reserved"]
        == 0
    )
    assert metrics["credits_reported"] is None
    assert metrics["scientific_evidence_per_credit"] is None
    assert metrics["zero_credit_reuse"] is True
    assert metrics["new_taxa_covered"] == metrics["new_characters_extracted"] == 1
    assert metrics["duplicate_sources_avoided"] == 0


@pytest.mark.asyncio
async def test_partial_coverage_refuses_completion_after_transport(tmp_path):
    provider = FirecrawlProvider(CONFIG, fixture_transport=transport)
    with pytest.raises(AcquisitionBlocked, match="MORPHOLOGY_COVERAGE_INCOMPLETE"):
        await acquire_matrix_sources(
            **services(tmp_path),
            provider=provider,
            corpus_audit=lambda: {
                "available": True,
                "complete": True,
                "documents": [],
                "identities": [],
            },
            load_held_source=lambda document: None,
            target_names=("Paphiopedilum delenatii",),
            required_predicates=("leaf_length", "leaf_width"),
        )
    assert provider.calls > 0


@pytest.mark.asyncio
async def test_missing_corpus_visibility_blocks_before_transport(tmp_path):
    provider = FirecrawlProvider(FirecrawlConfig())
    with pytest.raises(AcquisitionBlocked, match="EXISTING_CORPUS_AUDIT_UNAVAILABLE"):
        await acquire_matrix_sources(
            **services(tmp_path),
            provider=provider,
            corpus_audit=lambda: {"available": False, "complete": False},
        )
    assert provider.calls == 0


@pytest.mark.parametrize(
    ("candidate", "held"),
    [
        ({"source_url": URL + "?utm_source=test#section"}, {"source_url": URL}),
        ({"source_url": "https://doi.org/10.1234/ORCHID"}, {"doi": "10.1234/orchid"}),
        ({"content_hash": "sha"}, {"content_hash": "sha"}),
        ({"binding_fingerprint": "binding"}, {"binding_fingerprint": "binding"}),
        (
            {"title": "Orchid Revision", "authors": ["A Botanist"], "year": 2020},
            {"title": "Orchid revision.", "author": "A Botanist", "year": "2020"},
        ),
    ],
)
def test_held_identity_matches_without_acquiring(candidate, held):
    assert held_source_match(candidate, [held])


def test_title_alone_does_not_invent_duplicate_identity():
    assert not held_source_match({"title": "Orchid"}, [{"title": "Orchid"}])


def test_search_targets_only_declared_missing_predicates():
    queries = []

    def transport(endpoint, payload):
        queries.append(payload["query"])
        return 200, {"success": True, "data": {"web": []}}

    provider = FirecrawlProvider(
        FirecrawlConfig(enabled=True, domains=("flora.example",)),
        fixture_transport=transport,
    )
    provider.search(
        "Paphiopedilum", task_id="fixture", required_predicates=("leaf_width",)
    )
    assert '"leaf width"' in queries[0]
    with pytest.raises(AcquisitionBlocked, match="INVALID_REQUIRED_PREDICATES"):
        provider.search(
            "Paphiopedilum", task_id="fixture", required_predicates=("arbitrary_query",)
        )
