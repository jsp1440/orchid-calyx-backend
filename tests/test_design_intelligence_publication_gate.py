"""Publication-state enforcement for design-intelligence retrieval.

Indexing is not authority. Every retrieval path must hide a unit unless its exact
document version is current, approved and published, even when the unit was
indexed by mistake. In-memory repositories only; no database, no provider.
"""

from __future__ import annotations

import pytest

from app.design_intelligence import (
    DesignDomain,
    DesignIntelligenceService,
    DesignKnowledgeType,
    DesignReasoningService,
    DesignReviewDecision,
    MemoryDesignCorpusRepository,
    PublicationStatus,
    ReviewState,
)
from app.design_intelligence.acquisition import (
    AcquisitionMetadata,
    DesignDocumentAcquirer,
)
from app.design_intelligence.publication_gate import (
    DesignPublicationGateRequired,
    DesignPublicationStateUnavailable,
    corpus_publication_gate,
)
from app.design_intelligence.service import DesignSearchQuery

TEXT = (
    "# Relationship uncertainty\n"
    "Use plain language so that unknown evidence is never shown as zero. "
    "This guidance supports accessibility and reduced motion."
)


def _document_input(key="gate:doc", text=TEXT, revision=1):
    acquired = DesignDocumentAcquirer().acquire(
        "guide.md",
        text.encode(),
        AcquisitionMetadata(
            logical_key=key,
            title="Gate guide",
            authors=("curator",),
            publisher="test",
            source_uri="test://gate",
            license="test",
            publication_date=None,
            revision_id=revision,
            extraction_run_id=revision,
            anchor_ids=(revision,),
        ),
    )
    return type(acquired)(
        **{
            **acquired.__dict__,
            "requested_domains": (DesignDomain.ACCESSIBILITY,),
            "requested_types": (DesignKnowledgeType.GUIDELINE,),
        }
    )


@pytest.fixture
def stack():
    corpus_repository = MemoryDesignCorpusRepository()
    corpus = DesignIntelligenceService(corpus_repository)
    reasoning = DesignReasoningService(
        publication_gate=corpus_publication_gate(corpus_repository)
    )
    return corpus_repository, corpus, reasoning


def _import_and_index(stack, **kwargs):
    _, corpus, reasoning = stack
    document = corpus.import_document(_document_input(**kwargs))
    reasoning.index_document(document)  # indexed on purpose, before any review
    return document


def _approve(corpus, document, state=ReviewState.APPROVED):
    corpus.review(
        document.document_id, DesignReviewDecision(state, "curator", "Reviewed.")
    )


def _publish(corpus, document):
    corpus.publish(document.document_id, "curator", "Published.")


def _hits(reasoning, query="unknown evidence plain language"):
    return reasoning.search(query)["results"]


def test_a_mistakenly_indexed_unreviewed_document_is_not_retrievable(stack):
    _import_and_index(stack)
    assert stack[2].repository.units  # the unit really is in the index
    assert _hits(stack[2]) == []


def test_approved_but_unpublished_is_not_retrievable(stack):
    document = _import_and_index(stack)
    _approve(stack[1], document)
    assert _hits(stack[2]) == []


def test_approved_and_published_is_retrievable(stack):
    document = _import_and_index(stack)
    _approve(stack[1], document)
    _publish(stack[1], document)
    assert _hits(stack[2])


def test_a_rejection_after_publication_hides_the_document_in_both_search_paths(stack):
    document = _import_and_index(stack)
    _approve(stack[1], document)
    _publish(stack[1], document)
    assert _hits(stack[2])
    _approve(stack[1], document, ReviewState.REJECTED)
    assert _hits(stack[2]) == []
    assert (
        stack[1].search(DesignSearchQuery("unknown evidence plain language"))["total"]
        == 0
    )


@pytest.mark.parametrize(
    "status", [PublicationStatus.RETIRED, PublicationStatus.RETRACTED]
)
def test_retired_or_retracted_documents_are_hidden(stack, status):
    repository, corpus, reasoning = stack
    document = _import_and_index(stack)
    _approve(corpus, document)
    _publish(corpus, document)
    repository.publish(document.document_id, status, "curator", "Withdrawn.")
    assert _hits(reasoning) == []


def test_a_newer_unreviewed_version_hides_the_older_published_version(stack):
    repository, corpus, reasoning = stack
    first = _import_and_index(stack)
    _approve(corpus, first)
    _publish(corpus, first)
    assert _hits(reasoning)
    second = _import_and_index(stack, text=TEXT + "\nRevised statement.", revision=2)
    assert second.version == 2
    assert _hits(reasoning) == []
    assert repository.published_latest() == []


def test_related_concepts_from_unpublished_documents_are_not_disclosed(stack):
    _, corpus, reasoning = stack
    published = _import_and_index(stack, key="gate:published")
    _approve(corpus, published)
    _publish(corpus, published)
    _import_and_index(
        stack,
        key="gate:draft",
        text="# Draft\nThis draft recommendation contradicts the published rule about unknown evidence.",
        revision=2,
    )
    visible_ids = {
        unit.unit_id
        for unit in reasoning.repository.units
        if unit.document_id == published.document_id
    }
    for result in _hits(reasoning):
        assert result["document_id"] == published.document_id
        for related in result["related_concepts"]:
            assert related["unit_id"] in visible_ids


def test_an_unreadable_repository_fails_closed(stack):
    repository, corpus, reasoning = stack
    document = _import_and_index(stack)
    _approve(corpus, document)
    _publish(corpus, document)

    def broken(_):
        raise RuntimeError("database unavailable")

    repository.review_state = broken
    with pytest.raises(DesignPublicationStateUnavailable):
        _hits(reasoning)


def test_an_ungated_service_reports_that_publication_is_not_enforced():
    legacy = DesignReasoningService()
    assert legacy.publication_enforced is False
    assert (
        DesignReasoningService(publication_gate=lambda *_: False).publication_enforced
        is True
    )


def test_production_services_are_gated_and_share_the_same_gated_instance():
    from app.brain import education_design_routes
    from app.design_intelligence import routes
    from app.design_planning import routes as planning_routes

    assert routes.REASONING_SERVICE.publication_enforced is True
    assert education_design_routes.REASONING_SERVICE is routes.REASONING_SERVICE
    assert planning_routes.REASONING_SERVICE is routes.REASONING_SERVICE


def test_calyx_design_search_tool_refuses_an_ungated_service(monkeypatch):
    from app.calyx_agent import tools
    from app.design_intelligence import routes

    monkeypatch.setattr(routes, "REASONING_SERVICE", DesignReasoningService())
    with pytest.raises(DesignPublicationGateRequired):
        tools._design_search({"query": "relationship uncertainty"})


def test_calyx_design_search_tool_returns_nothing_unreviewed_and_something_after_review(
    monkeypatch,
):
    from app.calyx_agent import tools
    from app.design_intelligence import routes

    repository = MemoryDesignCorpusRepository()
    corpus = DesignIntelligenceService(repository)
    reasoning = DesignReasoningService(
        publication_gate=corpus_publication_gate(repository)
    )
    monkeypatch.setattr(routes, "REASONING_SERVICE", reasoning)
    document = corpus.import_document(_document_input())
    reasoning.index_document(document)

    assert (
        tools._design_search({"query": "unknown evidence plain language"}).data[
            "results"
        ]
        == []
    )
    _approve(corpus, document)
    _publish(corpus, document)
    assert tools._design_search({"query": "unknown evidence plain language"}).data[
        "results"
    ]


def test_gate_does_not_change_legacy_behavior_for_an_ungated_service(stack):
    _, corpus, _ = stack
    legacy = DesignReasoningService()
    document = corpus.import_document(_document_input())
    legacy.index_document(document)
    assert legacy.search("unknown evidence plain language")["results"]
