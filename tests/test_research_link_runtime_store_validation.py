"""Research Station evidence links resolve through the serving runtime stores.

Candidates and evidence aggregates are persisted by the BUILD-086 runtime repositories
(JSON snapshots), not by the relational 086a/086b tables. Link validation must answer
exactly what the serving candidate-knowledge / evidence-aggregation routes answer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.candidate_knowledge.routes as candidate_routes
import app.evidence_aggregation.routes as aggregation_routes
from app.candidate_knowledge.models import EvidenceInput, SourceAnchor
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.database import Base, get_db
from app.evidence_aggregation.models import CandidateInput
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService
from app.main import app
from app.research_workspace.models import (
    AuditEvent,
    Note,
    Project,
    ProjectDocument,
    ProjectEvidence,
    ProjectTaxon,
    SavedSearch,
)
from app.research_workspace.schemas import EvidenceLinkCreate, ProjectCreate
from app.research_workspace.service import (
    CanonicalReferenceValidator,
    ResearchWorkspaceError,
    ResearchWorkspaceService,
)

TABLES = [
    Project.__table__,
    SavedSearch.__table__,
    Note.__table__,
    ProjectTaxon.__table__,
    ProjectDocument.__table__,
    ProjectEvidence.__table__,
    AuditEvent.__table__,
]


def aggregate_candidate(i: int, value: str = "bee") -> CandidateInput:
    return CandidateInput(
        candidate_id=i,
        candidate_version=1,
        candidate_type="POLLINATOR_ASSOCIATION",
        normalized_subject="Dracula vampira",
        predicate="pollinated_by",
        object_value=value,
        source_revision_id=i,
        source_document_id=f"doc-{i}",
        source_anchor_ids=(i * 10,),
        source_class="PRIMARY",
        evidence_type="DIRECT_OBSERVATION",
        directness="DIRECT_OBSERVATION",
        source_lineage=f"study-{i}",
        document_hash=f"hash-{i}",
        confidence=0.8,
        display_policy="FULL_TEXT_ALLOWED",
    )


def build_aggregate_store(*candidate_ids: int):
    repository = MemoryAggregateRepository()
    service = EvidenceAggregationService(repository)
    plan = service.preview([aggregate_candidate(i) for i in candidate_ids])
    service.execute(plan["aggregate_run_id"])
    return repository, service


def candidate_evidence(source_id: int = 1, text: str = "Masdevallia occurs in cloud forest."):
    return EvidenceInput(
        "TAXONOMIC_TREATMENT",
        source_id,
        source_id,
        source_id,
        text,
        (
            SourceAnchor(
                source_id * 10 + 1,
                page_number=2,
                char_start=0,
                char_end=len(text),
                locator={"page": 2, "confidence": 0.95},
            ),
        ),
        display_policy="FULL_TEXT_ALLOWED",
        metadata={"subject": "Masdevallia", "source_confidence": 0.8},
    )


def build_candidate_store(*evidence: EvidenceInput):
    repository = MemoryCandidateRepository()
    service = CandidateExtractionService(repository)
    plan = service.preview(list(evidence))
    service.execute(plan["candidate_run_id"])
    return repository, service


class FailingSnapshotRepository(MemoryAggregateRepository):
    """Models PostgresStateMixin whose snapshot read fails."""

    def refresh(self):
        raise RuntimeError("database unreachable")


class RelationalSessionMustNotBeUsed:
    def execute(self, *args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("runtime-store kinds must not query relational tables")


def validator(aggregates=None, candidates=None) -> CanonicalReferenceValidator:
    return CanonicalReferenceValidator(
        RelationalSessionMustNotBeUsed(),  # type: ignore[arg-type]
        aggregate_repository=(lambda: aggregates),
        candidate_repository=(lambda: candidates),
    )


def error_code(callable_) -> tuple[str, int]:
    with pytest.raises(ResearchWorkspaceError) as caught:
        callable_()
    return caught.value.code, caught.value.status


def test_aggregate_created_by_real_aggregation_service_validates():
    repository, _ = build_aggregate_store(1, 2)
    aggregate_id = repository.versions[0]["aggregate_id"]
    validator(aggregates=repository).require("AGGREGATE", str(aggregate_id))


def test_superseded_or_withdrawn_aggregate_is_rejected_like_the_route_404():
    repository, service = build_aggregate_store(1, 2)
    aggregate_id = repository.versions[0]["aggregate_id"]
    service.supersede(aggregate_id, "retracted", "owner")
    assert repository.current_aggregate(aggregate_id) is None
    assert error_code(
        lambda: validator(aggregates=repository).require("AGGREGATE", str(aggregate_id))
    ) == ("AGGREGATE_NOT_FOUND", 404)


def test_aggregate_with_new_version_still_resolves_to_its_current_version():
    repository, service = build_aggregate_store(1, 2)
    plan = service.preview([aggregate_candidate(i) for i in (1, 2, 3)])
    service.execute(plan["aggregate_run_id"])
    assert len(repository.versions) == 2
    aggregate_id = repository.versions[-1]["aggregate_id"]
    assert repository.versions[0]["aggregate_id"] == aggregate_id
    validator(aggregates=repository).require("AGGREGATE", str(aggregate_id))


def test_unknown_or_non_canonical_aggregate_identifiers_are_not_found():
    repository, _ = build_aggregate_store(1)
    aggregate_id = repository.versions[0]["aggregate_id"]
    version_id = repository.versions[0]["aggregate_version_id"]
    assert version_id != aggregate_id
    for identifier in ("999", str(version_id), f"0{aggregate_id}", f" {aggregate_id}", "abc", "-1"):
        assert error_code(
            lambda identifier=identifier: validator(aggregates=repository).require(
                "AGGREGATE", identifier
            )
        ) == ("AGGREGATE_NOT_FOUND", 404)


def test_candidate_created_by_real_candidate_service_validates():
    repository, _ = build_candidate_store(candidate_evidence())
    candidate_id = repository.candidates[0]["candidate_id"]
    validator(candidates=repository).require("CANDIDATE", str(candidate_id))
    assert error_code(
        lambda: validator(candidates=repository).require("CANDIDATE", "999")
    ) == ("CANDIDATE_NOT_FOUND", 404)


def test_superseded_candidate_version_cannot_be_newly_linked():
    repository, _ = build_candidate_store(candidate_evidence())
    service = CandidateExtractionService(repository)
    plan = service.preview([candidate_evidence(2, "Masdevallia occurs in paramo.")])
    service.execute(plan["candidate_run_id"])
    old, new = repository.candidates[0], repository.candidates[-1]
    assert old["active"] is False and new["active"] is True
    assert error_code(
        lambda: validator(candidates=repository).require("CANDIDATE", str(old["candidate_id"]))
    ) == ("CANDIDATE_NOT_FOUND", 404)
    validator(candidates=repository).require("CANDIDATE", str(new["candidate_id"]))


@pytest.mark.parametrize("kind", ["AGGREGATE", "CANDIDATE"])
def test_unavailable_runtime_store_fails_closed(kind):
    def unavailable():
        raise RuntimeError("AGGREGATION_DATABASE_UNAVAILABLE")

    for provider in (unavailable, lambda: None):
        checker = CanonicalReferenceValidator(
            RelationalSessionMustNotBeUsed(),  # type: ignore[arg-type]
            aggregate_repository=provider,
            candidate_repository=provider,
        )
        assert error_code(lambda checker=checker: checker.require(kind, "1")) == (
            "REFERENCE_VALIDATION_UNAVAILABLE",
            503,
        )


def test_default_providers_fail_closed_when_serving_repository_is_unavailable(monkeypatch):
    monkeypatch.setattr(aggregation_routes, "REPOSITORY", None)
    monkeypatch.setattr(aggregation_routes, "SERVICE", None)
    monkeypatch.setattr(candidate_routes, "REPOSITORY", None)
    monkeypatch.setattr(candidate_routes, "SERVICE", None)
    checker = CanonicalReferenceValidator(RelationalSessionMustNotBeUsed())  # type: ignore[arg-type]
    for kind in ("AGGREGATE", "CANDIDATE"):
        assert error_code(lambda kind=kind: checker.require(kind, "1")) == (
            "REFERENCE_VALIDATION_UNAVAILABLE",
            503,
        )

    failing = FailingSnapshotRepository()
    monkeypatch.setattr(aggregation_routes, "REPOSITORY", failing)
    monkeypatch.setattr(
        aggregation_routes, "SERVICE", EvidenceAggregationService(failing)
    )
    assert error_code(lambda: checker.require("AGGREGATE", "1")) == (
        "REFERENCE_VALIDATION_UNAVAILABLE",
        503,
    )


@pytest.fixture
def serving_stores(monkeypatch):
    aggregates, aggregate_service = build_aggregate_store(1, 2)
    candidates, candidate_service = build_candidate_store(candidate_evidence())
    monkeypatch.setattr(aggregation_routes, "REPOSITORY", aggregates)
    monkeypatch.setattr(aggregation_routes, "SERVICE", aggregate_service)
    monkeypatch.setattr(candidate_routes, "REPOSITORY", candidates)
    monkeypatch.setattr(candidate_routes, "SERVICE", candidate_service)
    return aggregates, aggregate_service, candidates


@pytest.fixture
def client(monkeypatch, serving_stores):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_API_KEY", "research-api-key")
    monkeypatch.setenv("CORS_ALLOW_ORIGIN", "https://example.test")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(engine, tables=TABLES)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


HEADERS = {"X-API-Key": "research-api-key"}


def test_http_link_validation_matches_serving_routes(client, serving_stores):
    aggregates, aggregate_service, candidates = serving_stores
    aggregate_id = aggregates.versions[0]["aggregate_id"]
    candidate_id = candidates.candidates[0]["candidate_id"]
    project = client.post(
        "/api/research/projects",
        json=ProjectCreate(title="Link validation", status="ACTIVE").model_dump(),
        headers=HEADERS,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["project_id"]

    def link(kind, identifier):
        return client.post(
            f"/api/research/projects/{project_id}/evidence",
            json={"evidence_kind": kind, "evidence_id": identifier},
            headers=HEADERS,
        )

    served = client.get(f"/api/evidence-aggregation/aggregates/{aggregate_id}", headers=HEADERS)
    assert served.status_code == 200
    assert link("AGGREGATE", str(aggregate_id)).status_code == 201

    served = client.get(f"/api/candidate-knowledge/candidates/{candidate_id}", headers=HEADERS)
    assert served.status_code == 200
    assert link("CANDIDATE", str(candidate_id)).status_code == 201

    aggregate_service.supersede(aggregate_id, "retracted", "owner")
    served = client.get(f"/api/evidence-aggregation/aggregates/{aggregate_id}", headers=HEADERS)
    assert served.status_code == 404
    rejected = link("AGGREGATE", str(aggregate_id))
    assert rejected.status_code == 404
    assert "AGGREGATE_NOT_FOUND" in rejected.text

    assert client.get("/api/evidence-aggregation/aggregates/424242", headers=HEADERS).status_code == 404
    assert link("AGGREGATE", "424242").status_code == 404


def test_service_level_link_through_default_validator(serving_stores):
    aggregates, _, candidates = serving_stores
    engine = create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"research_station": None}}
    )
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as db:
        service = ResearchWorkspaceService(db)
        project = service.create_project(
            "owner-a", ProjectCreate(title="Default validator", status="ACTIVE")
        )
        service.add_evidence(
            project["project_id"],
            "owner-a",
            EvidenceLinkCreate(
                evidence_kind="AGGREGATE",
                evidence_id=str(aggregates.versions[0]["aggregate_id"]),
            ),
        )
        service.add_evidence(
            project["project_id"],
            "owner-a",
            EvidenceLinkCreate(
                evidence_kind="CANDIDATE",
                evidence_id=str(candidates.candidates[0]["candidate_id"]),
            ),
        )


def test_validator_no_longer_reads_unwritten_relational_candidate_tables():
    queries = " ".join(CanonicalReferenceValidator.QUERIES.values())
    assert "aggregate_assertions" not in queries
    assert "oc_candidate_knowledge.candidates" not in queries
