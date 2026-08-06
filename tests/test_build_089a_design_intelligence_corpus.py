import hashlib
import os
import uuid
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.design_intelligence import (
    DesignDocumentInput,
    DesignDomain,
    DesignIntelligenceService,
    DesignKnowledgeType,
    DesignProvenance,
    DesignReviewDecision,
    DesignSearchQuery,
    MemoryDesignCorpusRepository,
    ReviewState,
)
from app.security import verify_owner_or_api_key


def document(
    key: str,
    title: str,
    content: str,
    revision: int,
    topics: tuple[str, ...] = (),
) -> DesignDocumentInput:
    return DesignDocumentInput(
        logical_key=key,
        title=title,
        content=content,
        document_type="REFERENCE",
        authors=("Design Researcher",),
        publication_date=date(2025, 1, 2),
        license_metadata={"license": "CC-BY-4.0", "display": "FULL_TEXT_ALLOWED"},
        provenance=DesignProvenance(
            source_system="oc_document_intelligence",
            source_id=f"record:{revision}",
            revision_id=revision,
            extraction_run_id=revision + 100,
            anchor_ids=(revision + 1000,),
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            evidence_link_ids=(revision + 2000,),
        ),
        topics=topics,
        source_metadata={"publisher": "Orchid Continuum test corpus"},
    )


def approve_and_publish(service, item):
    service.review(
        item.document_id,
        DesignReviewDecision(
            ReviewState.APPROVED,
            "design-reviewer",
            "Verified classification, provenance, and license",
            {"review_queue": "design-intelligence"},
        ),
    )
    service.publish(item.document_id, "publication-service", "Approved corpus entry")


def test_all_required_domains_and_knowledge_types_are_closed_vocabularies():
    assert len(DesignDomain) == 14
    assert len(DesignKnowledgeType) == 10
    assert {item.value for item in DesignDomain} >= {
        "DASHBOARD_DESIGN",
        "ACCESSIBILITY",
        "LEARNING_SCIENCES",
        "SCIENTIFIC_VISUALIZATION",
        "COMPONENT_LIBRARIES",
    }
    assert {item.value for item in DesignKnowledgeType} >= {
        "DESIGN_PRINCIPLE",
        "ANTI_PATTERN",
        "ACCESSIBILITY_REQUIREMENT",
        "VISUALIZATION_TECHNIQUE",
    }


def test_import_is_versioned_immutable_and_preserves_exact_provenance():
    repository = MemoryDesignCorpusRepository()
    service = DesignIntelligenceService(repository)
    first = service.import_document(
        document(
            "dashboard-guidance",
            "Dashboard design guideline",
            "A dashboard guideline should use clear hierarchy and status display patterns.",
            1,
            ("dashboards", "information hierarchy"),
        )
    )
    second = service.import_document(
        document(
            "dashboard-guidance",
            "Dashboard design guideline, revised",
            "A dashboard best practice should prioritize clear hierarchy and status display patterns.",
            2,
            ("dashboards", "information hierarchy"),
        )
    )
    assert (first.version, second.version) == (1, 2)
    assert first.provenance.revision_id == 1 and first.provenance.anchor_ids == (1001,)
    assert second.domains == (DesignDomain.DASHBOARD_DESIGN,)
    with pytest.raises(FrozenInstanceError):
        first.title = "mutated"
    with pytest.raises(ValueError, match="PROVENANCE_MISMATCH"):
        bad = document("bad", "Bad", "dashboard guideline", 3)
        service.import_document(
            DesignDocumentInput(
                **{**bad.__dict__, "provenance": first.provenance}
            )
        )


def test_review_and_publication_are_append_only_and_fail_closed():
    repository = MemoryDesignCorpusRepository()
    service = DesignIntelligenceService(repository)
    item = service.import_document(
        document(
            "wcag",
            "Accessibility standard",
            "WCAG accessibility requirement: keyboard access and contrast are success criteria.",
            10,
        )
    )
    with pytest.raises(ValueError, match="REVIEW_APPROVAL_REQUIRED"):
        service.publish(item.document_id, "publisher", "too early")
    approve_and_publish(service, item)
    assert repository.review_state(item.document_id) is ReviewState.APPROVED
    assert len(repository.audit_events) == 3
    with pytest.raises(ValueError, match="INVALID_DESIGN_PUBLICATION_TRANSITION"):
        service.publish(item.document_id, "publisher", "duplicate")


def test_retrieval_answers_required_future_ui_generation_questions():
    repository = MemoryDesignCorpusRepository()
    service = DesignIntelligenceService(repository)
    fixtures = (
        document("dashboard", "Dashboard guidance", "Dashboard guideline and status display pattern.", 20),
        document("accessibility", "Accessible interfaces", "WCAG accessibility requirement for keyboard and contrast.", 21),
        document("mayer", "Mayer multimedia learning", "Mayer multimedia learning theory reduces extraneous cognitive load.", 22),
        document("motion", "Motion recommendations", "Motion design recommendation: animation and transition must honor reduced motion.", 23),
        document("visualization", "Scientific visualization", "Scientific visualization guideline for uncertainty visualization and chart encoding.", 24),
    )
    for value in fixtures:
        approve_and_publish(service, service.import_document(value))
    questions = {
        "Find dashboard guidance.": "dashboard",
        "Find accessibility guidance.": "accessibility",
        "Find Mayer multimedia learning.": "mayer",
        "Find motion design recommendations.": "motion",
        "Find scientific visualization references.": "visualization",
    }
    for query, expected in questions.items():
        result = service.search(DesignSearchQuery(query))
        assert result["results"][0]["logical_key"] == expected
        assert result["results"][0]["provenance"]["revision_id"] > 0
        assert 0 < result["results"][0]["confidence"] <= 1
        assert result["results"][0]["publication_status"] == "PUBLISHED"
    draft = service.import_document(
        document("draft", "Dashboard draft", "Dashboard guideline not reviewed.", 25)
    )
    assert draft.document_id
    assert all(
        item["logical_key"] != "draft"
        for item in service.search(DesignSearchQuery("dashboard"))["results"]
    )


def test_authenticated_retrieval_route_is_read_only(monkeypatch):
    from app.design_intelligence import routes

    repository = MemoryDesignCorpusRepository()
    service = DesignIntelligenceService(repository)
    item = service.import_document(
        document("route", "Dashboard route", "Dashboard design guideline.", 30)
    )
    approve_and_publish(service, item)
    monkeypatch.setattr(routes, "REPOSITORY", repository)
    monkeypatch.setattr(routes, "SERVICE", service)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test"}
    client = TestClient(app)
    response = client.post(
        "/api/design-intelligence/search", json={"query": "dashboard guidance"}
    )
    assert response.status_code == 200 and response.json()["total"] == 1
    configuration = client.get("/api/design-intelligence/configuration").json()
    assert configuration["read_only"] and len(configuration["domains"]) == 14


def test_migration_is_additive_indexed_and_append_only():
    sql = Path("migrations/089a_design_intelligence_corpus.sql").read_text()
    assert "DROP TABLE" not in sql and "TRUNCATE" not in sql
    assert "protect_089a_" in sql and "DESIGN_INTELLIGENCE_RECORDS_ARE_APPEND_ONLY" in sql
    assert "design_retrieval_fts_idx" in sql
    assert "REFERENCES oc_import.document_revisions" in sql
    assert "REFERENCES oc_document_intelligence.source_anchors" in sql


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_authoritative_repository_and_immutability():
    import psycopg

    from app.design_intelligence.postgres_repository import (
        PostgresDesignCorpusRepository,
    )

    dsn = os.environ["TEST_DATABASE_URL"]
    suffix = uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS oc_import")
        con.execute(
            "CREATE TABLE IF NOT EXISTS oc_import.document_revisions(revision_id BIGINT PRIMARY KEY)"
        )
        con.execute("CREATE SCHEMA IF NOT EXISTS oc_document_intelligence")
        con.execute(
            "CREATE TABLE IF NOT EXISTS oc_document_intelligence.extraction_runs(extraction_run_id BIGINT PRIMARY KEY)"
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS oc_document_intelligence.source_anchors(
            anchor_id BIGINT PRIMARY KEY,revision_id BIGINT NOT NULL,
            extraction_run_id BIGINT NOT NULL)"""
        )
        con.execute(Path("migrations/089a_design_intelligence_corpus.sql").read_text())
        con.execute(
            "INSERT INTO oc_import.document_revisions VALUES(40) ON CONFLICT DO NOTHING"
        )
        con.execute(
            "INSERT INTO oc_document_intelligence.extraction_runs VALUES(140) ON CONFLICT DO NOTHING"
        )
        con.execute(
            "INSERT INTO oc_document_intelligence.source_anchors VALUES(1040,40,140) ON CONFLICT DO NOTHING"
        )
    repository = PostgresDesignCorpusRepository(dsn)
    service = DesignIntelligenceService(repository)
    item = service.import_document(
        document(
            f"postgres-dashboard-{suffix}",
            "PostgreSQL dashboard guidance",
            "Dashboard design guideline with a status display pattern.",
            40,
        )
    )
    approve_and_publish(service, item)
    result = service.search(DesignSearchQuery("dashboard guidance"))
    match = next(
        value
        for value in result["results"]
        if value["logical_key"] == f"postgres-dashboard-{suffix}"
    )
    assert match["provenance"]["anchor_ids"] == (1040,)
    with psycopg.connect(dsn, autocommit=True) as con, pytest.raises(psycopg.errors.RaiseException):
            con.execute(
                "UPDATE oc_design_intelligence.documents SET title='mutated' WHERE document_id=%s",
                (item.document_id,),
            )
