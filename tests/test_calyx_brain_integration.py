from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.brain import routes
from app.brain.ledger_bridge import InferenceLedgerBridge
from app.brain.reasoning import InferenceEngine, InferenceType
from app.database import Base, get_db
from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    ReviewDecision,
    ReviewOutcome,
    UncertaintyMarker,
)
from app.reasoning_ledger.operational_service import OperationalReasoningLedgerService
from app.reasoning_ledger.persistence import TABLES, StaleLedgerVersionError
from app.research_workspace.models import Project
from app.security import verify_owner_or_api_key
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={
            "schema_translate_map": {
                "research_station": None,
                "reasoning_ledger": None,
            }
        },
    )
    Base.metadata.create_all(engine, tables=[Project.__table__, *TABLES])
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _graph(*, ambiguous: bool = False, evidence: bool = True):
    nodes = [
        Node(1, "taxon", "taxon:a", "Orchid A"),
        Node(2, "habitat", "habitat:cloud", "Cloud forest"),
        Node(3, "taxon", "taxon:b", "Orchid B"),
    ]
    if ambiguous:
        nodes.append(Node(4, "taxon", "taxon:b", "Duplicate Orchid B"))
    edges = []
    if evidence:
        edges = [
            Edge(
                10,
                "occurs_in",
                1,
                2,
                "literature.evidence",
                "e-1",
                "observed",
                0.9,
                "high",
                None,
                {
                    "paper_id": "paper-1",
                    "evidence_id": "e-1",
                    "content_hash": "a" * 64,
                    "citation": "Paper one",
                    "connector_id": "crossref",
                },
            ),
            Edge(
                11,
                "occurs_in",
                3,
                2,
                "literature.evidence",
                "e-2",
                "observed",
                0.8,
                "high",
                None,
                {
                    "paper_id": "paper-2",
                    "evidence_id": "e-2",
                    "content_hash": "b" * 64,
                    "citation": "Paper two",
                },
            ),
        ]
    return InMemoryGraphRepository(nodes, edges)


def _project(db: Session, owner: str = "owner-a") -> str:
    project = Project(owner_subject=owner, title="Integrated Brain", description="")
    db.add(project)
    db.commit()
    return str(project.project_id)


def _ledger(db: Session, project_id: str):
    return OperationalReasoningLedgerService(db).create(
        owner="owner-a",
        project_id=project_id,
        title="Inference review",
        description="",
    )[0]


def _artifact(graph):
    return InferenceEngine(graph).infer(1, InferenceType.HABITAT_SIMILARITY)["results"][
        0
    ]


def _submit(db, graph, ledger, project_id, *, expected_version=None, owner="owner-a"):
    artifact = _artifact(graph)
    return InferenceLedgerBridge(db, graph).submit(
        ledger_id=str(ledger.ledger_id),
        project_id=project_id,
        owner=owner,
        expected_version=expected_version or ledger.version,
        subject_node_id=1,
        inference_type=InferenceType.HABITAT_SIMILARITY,
        candidate_node_id=3,
        inference_content_hash=artifact["inference_content_hash"],
    )


def test_deterministic_submission_revision_audit_duplicate_and_no_graph_write():
    session_local = _database()
    graph = _graph()
    before = (graph.all_nodes(), graph.all_edges())
    with session_local() as db:
        project_id = _project(db)
        ledger = _ledger(db, project_id)
        artifact = _artifact(graph)
        assert artifact == _artifact(graph)
        first = _submit(db, graph, ledger, project_id)
        assert first["created"] is True
        assert first["ledger"].version == 2
        entry = first["ledger"].entries[-1]
        assert (
            entry.attributes["inference_content_hash"]
            == artifact["inference_content_hash"]
        )
        assert entry.attributes["literature_evidence_references"]
        assert entry.attributes["automatically_approved"] is False
        assert entry.attributes["automatically_published"] is False
        history = OperationalReasoningLedgerService(db).history(
            str(ledger.ledger_id), "owner-a"
        )
        assert [item.version for item in history["revisions"]] == [1, 2]
        assert history["audit_events"][-1]["event_type"] == (
            "INFERENCE_CANDIDATE_APPENDED"
        )

        duplicate = _submit(db, graph, first["ledger"], project_id, expected_version=2)
        assert duplicate["duplicate_reused"] is True
        assert duplicate["entry_id"] == first["entry_id"]
        assert duplicate["ledger"].version == 2
        assert (
            len(
                OperationalReasoningLedgerService(db).history(
                    str(ledger.ledger_id), "owner-a"
                )["audit_events"]
            )
            == 2
        )
    assert (graph.all_nodes(), graph.all_edges()) == before


def test_stale_cross_tenant_cross_project_missing_and_ambiguous_rejected():
    session_local = _database()
    with session_local() as db:
        project_id = _project(db)
        other_project_id = _project(db)
        ledger = _ledger(db, project_id)
        created = _submit(db, _graph(), ledger, project_id)
        with pytest.raises(StaleLedgerVersionError):
            _submit(db, _graph(), created["ledger"], project_id, expected_version=1)
        with pytest.raises(Exception, match="ledger not found"):
            _submit(db, _graph(), created["ledger"], project_id, owner="owner-b")
        with pytest.raises(Exception, match="PROJECT_SCOPE_MISMATCH"):
            _submit(db, _graph(), created["ledger"], other_project_id)
        with pytest.raises(Exception, match="MISSING_INFERENCE_EVIDENCE"):
            InferenceLedgerBridge(db, _graph(evidence=False)).submit(
                ledger_id=str(ledger.ledger_id),
                project_id=project_id,
                owner="owner-a",
                expected_version=2,
                subject_node_id=1,
                inference_type=InferenceType.HABITAT_SIMILARITY,
                candidate_node_id=3,
                inference_content_hash="a" * 64,
            )
        with pytest.raises(Exception, match="AMBIGUOUS_CANONICAL_IDENTITY"):
            _submit(db, _graph(ambiguous=True), created["ledger"], project_id)


def test_inference_mutation_invalidates_prior_approval():
    session_local = _database()
    with session_local() as db:
        project_id = _project(db)
        service = OperationalReasoningLedgerService(db)
        ledger = _ledger(db, project_id)
        ledger = service.append(
            str(ledger.ledger_id),
            LedgerEntry(
                kind=LedgerEntryKind.CONCLUSION,
                text="Prior conclusion",
                author="owner-a",
                tenant_id="owner-a",
                project_id=project_id,
                uncertainty=UncertaintyMarker(confidence=0.9),
            ),
            owner="owner-a",
            expected_version=1,
        )
        ledger = service.review(
            str(ledger.ledger_id),
            ReviewDecision(
                reviewer="owner-a",
                outcome=ReviewOutcome.APPROVED,
                rationale="Reviewed before new inference",
            ),
            owner="owner-a",
            expected_version=2,
        )
        assert ledger.has_human_approval
        updated = _submit(db, _graph(), ledger, project_id)["ledger"]
        assert updated.version == 4
        assert not updated.has_human_approval


def test_submission_api_authentication_and_private_reasoning_rejection():
    session_local = _database()
    with session_local() as db:
        project_id = _project(db)
        ledger = _ledger(db, project_id)
    graph = _graph()
    artifact = _artifact(graph)
    application = FastAPI()
    application.include_router(routes.router)

    def db_override():
        with session_local() as db:
            yield db

    application.dependency_overrides[get_db] = db_override
    application.dependency_overrides[routes.get_graph_repository] = lambda: graph
    api = TestClient(application)
    url = "/brain/inferences/1/submit-to-ledger"
    payload = {
        "ledger_id": str(ledger.ledger_id),
        "project_id": project_id,
        "expected_version": 1,
        "inference_type": "habitat_similarity",
        "candidate_node_id": 3,
        "inference_content_hash": artifact["inference_content_hash"],
    }
    assert api.post(url, json=payload).status_code == 401
    application.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-a"
    }
    private = api.post(url, json={**payload, "chain_of_thought": "do not store"})
    assert private.status_code == 422
    submitted = api.post(url, json=payload)
    assert submitted.status_code == 201
    assert submitted.json()["automatically_published"] is False
