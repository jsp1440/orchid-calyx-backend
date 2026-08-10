from dataclasses import asdict

from fastapi.testclient import TestClient

from app.main import app
from app.scientific_synthesis.models import (
    BibliographicRecord,
    EvidenceAnchor,
    EvidenceClass,
    EvidenceMatrixRow,
    VerificationState,
)
from app.scientific_synthesis.pipeline import (
    EvidenceClassificationDecision,
    ResearchToArticleMissionService,
)


def _source(source_id: str, doi: str):
    return BibliographicRecord(
        source_id=source_id,
        title=f"Verified orchid study {doi}",
        authors=("Ada Researcher",),
        year=2026,
        journal="Journal of Orchid Science",
        doi=doi,
        verification_state=VerificationState.VERIFIED_AUTHORITY,
        verification_provider="crossref",
        verification_identifier=doi,
    )


def _row(
    evidence_id: str,
    source_id: str,
    *,
    outcome: str,
    result: str,
    polarity: str | None = "positive",
):
    return EvidenceMatrixRow(
        evidence_id=evidence_id,
        source_id=source_id,
        evidence_class=EvidenceClass.OBSERVATIONAL,
        anchors=(
            EvidenceAnchor(
                anchor_id=f"anchor:{evidence_id}",
                source_id=source_id,
                source_revision_id="revision-1",
                locator={"page": 4, "start": 10, "end": 80},
                content_hash=f"source-hash:{source_id}",
                excerpt_hash=f"excerpt-hash:{evidence_id}",
            ),
        ),
        taxon="Phalaenopsis",
        outcome=outcome,
        method="source-bound extracted result",
        result=result,
        metadata={"polarity": polarity} if polarity is not None else {},
    )


def _benchmark():
    bibliography = (
        _source("doi:10.1000/foliar.1", "10.1000/foliar.1"),
        _source("doi:10.1000/foliar.2", "10.1000/foliar.2"),
    )
    rows = (
        _row(
            "ev-foliar",
            "doi:10.1000/foliar.1",
            outcome="foliar nitrogen uptake",
            result="Applied nitrogen was detected after leaf treatment.",
        ),
        _row(
            "ev-root",
            "doi:10.1000/foliar.2",
            outcome="root versus leaf uptake",
            result="Root treatment produced greater uptake than leaf treatment.",
        ),
    )
    decisions = (
        EvidenceClassificationDecision(
            evidence_id="ev-foliar",
            evidence_class=EvidenceClass.DIRECT_TRACER,
            reviewer_id="reviewer-botany-1",
            rationale="Methods and results explicitly use a labeled tracer applied to the leaf.",
        ),
        EvidenceClassificationDecision(
            evidence_id="ev-root",
            evidence_class=EvidenceClass.CONTROLLED_EXPERIMENT,
            reviewer_id="reviewer-botany-1",
            rationale="Methods explicitly compare root and leaf application under controlled conditions.",
        ),
    )
    return bibliography, rows, decisions


def test_foliar_feeding_benchmark_runs_to_grounded_article():
    bibliography, rows, decisions = _benchmark()
    result = ResearchToArticleMissionService().run(
        question="Do orchids respond to foliar feeding?",
        title="Can Orchids Really Foliar Feed?",
        audience="orchid society newsletter",
        format="newsletter_article",
        bibliography=bibliography,
        evidence_rows=rows,
        classification_decisions=decisions,
    )

    assert result["state"] == "RESEARCH_TO_ARTICLE_COMPLETE"
    assert result["audit"]["publication_ready"] is True
    assert result["human_review_required"] is True
    assert result["published"] is False
    assert "# Can Orchids Really Foliar Feed?" in result["article_markdown"]
    scientific_sentences = [
        value for value in result["article"]["sentences"] if value["scientific"]
    ]
    assert len(scientific_sentences) == 2
    assert all(value["claim_ids"] for value in scientific_sentences)
    assert {value["kind"].value for value in result["claims"]} == {"DIRECT"}
    assert len(result["figure_briefs"]) == len(result["claims"])


def test_structural_record_count_is_grounded_by_claim_support_set():
    bibliography, _, _ = _benchmark()
    rows = (
        _row(
            "ev-a",
            bibliography[0].source_id,
            outcome="foliar uptake",
            result="Leaf-applied nitrogen was detected.",
        ),
        _row(
            "ev-b",
            bibliography[1].source_id,
            outcome="foliar uptake",
            result="Leaf uptake was observed under the study conditions.",
        ),
    )

    result = ResearchToArticleMissionService().run(
        question="Can orchids absorb nutrients through leaves?",
        title="Foliar Uptake",
        audience="researcher",
        format="evidence_brief",
        bibliography=bibliography,
        evidence_rows=rows,
    )

    assert "Across 2 source-bound evidence records" in result["claims"][0]["text"]
    assert result["audit"]["quantitative_errors"] == []
    assert result["audit"]["publication_ready"] is True


def test_missing_polarity_never_becomes_directional_consistency():
    bibliography, _, _ = _benchmark()
    rows = (
        _row(
            "ev-known",
            bibliography[0].source_id,
            outcome="foliar uptake",
            result="Leaf uptake was observed.",
        ),
        _row(
            "ev-unknown",
            bibliography[1].source_id,
            outcome="foliar uptake",
            result="A second study reported a context-dependent response.",
            polarity=None,
        ),
    )

    result = ResearchToArticleMissionService().run(
        question="Can orchids absorb nutrients through leaves?",
        title="Foliar Uptake",
        audience="researcher",
        format="evidence_brief",
        bibliography=bibliography,
        evidence_rows=rows,
    )

    claim = result["claims"][0]
    assert "mixed or uncertain" in claim["text"]
    assert "directionally consistent" not in claim["text"]
    assert "ev-unknown" in claim["conflicting_evidence_ids"]


def test_evidence_class_upgrade_requires_review_provenance():
    bibliography, rows, _ = _benchmark()
    bad = EvidenceClassificationDecision(
        evidence_id="ev-foliar",
        evidence_class=EvidenceClass.DIRECT_TRACER,
        reviewer_id=" ",
        rationale=" ",
    )
    try:
        ResearchToArticleMissionService().run(
            question="Do orchids respond to foliar feeding?",
            title="Foliar Feeding",
            audience="newsletter",
            format="newsletter_article",
            bibliography=bibliography,
            evidence_rows=rows,
            classification_decisions=(bad,),
        )
    except ValueError as exc:
        assert str(exc) == "CLASSIFICATION_REVIEW_PROVENANCE_REQUIRED"
    else:
        raise AssertionError("unreviewed evidence-class upgrade was accepted")


def test_unverified_bibliography_blocks_generated_article():
    bibliography, rows, decisions = _benchmark()
    unsafe = (
        BibliographicRecord(
            source_id=bibliography[0].source_id,
            title=bibliography[0].title,
            authors=bibliography[0].authors,
            year=bibliography[0].year,
            journal=bibliography[0].journal,
            doi=bibliography[0].doi,
            verification_state=VerificationState.UNVERIFIED,
        ),
        bibliography[1],
    )
    result = ResearchToArticleMissionService().run(
        question="Do orchids respond to foliar feeding?",
        title="Foliar Feeding",
        audience="newsletter",
        format="newsletter_article",
        bibliography=unsafe,
        evidence_rows=rows,
        classification_decisions=decisions,
    )

    assert result["state"] == "RESEARCH_TO_ARTICLE_BLOCKED"
    assert result["audit"]["publication_ready"] is False


def test_research_article_api_is_authenticated(monkeypatch):
    bibliography, rows, decisions = _benchmark()
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    payload = {
        "question": "Do orchids respond to foliar feeding?",
        "title": "Can Orchids Really Foliar Feed?",
        "audience": "orchid society newsletter",
        "format": "newsletter_article",
        "bibliography": [asdict(record) for record in bibliography],
        "evidence_rows": [asdict(row) for row in rows],
        "classification_decisions": [asdict(decision) for decision in decisions],
    }

    with TestClient(app) as client:
        path = "/api/scientific-interpretation/research-article/run"
        assert client.post(path, json=payload).status_code == 401
        response = client.post(path, json=payload, headers={"X-API-Key": "test-key"})

    assert response.status_code == 200
    assert response.json()["state"] == "RESEARCH_TO_ARTICLE_COMPLETE"
