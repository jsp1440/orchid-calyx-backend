from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.semantic.dependencies import get_candidate_repository, get_extraction_service, get_review_repository
from app.semantic.models import EvidenceDraft, ExtractionStage, STAGE_TRANSITIONS, validate_transition
from app.semantic.repositories import semantic_database_url
from app.semantic.routers import router
from app.semantic.schemas import CandidatePatch
from app.semantic.services import ExtractionOrchestrationService, RuleBasedSemanticExtractor, candidate_changes


class MemoryRepository:
    def __init__(self) -> None:
        self.documents = {7: {"id": 7, "extracted_text": "Dracula lafleurii is pollinated by Euglossa.", "sha256": "a" * 64}}
        self.sessions: dict[int, dict[str, Any]] = {}
        self.evidence: dict[int, dict[str, Any]] = {}
        self.entities: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []

    def create_session(self, document_id: int, actor: str, provenance: dict[str, Any]) -> dict[str, Any]:
        session = {"id": 1, "document_id": document_id, "stage": "QUEUED", "provenance": provenance, "created_by": actor}
        self.sessions[1] = session
        self.audit.append({"action": "SESSION_CREATED", "actor": actor})
        return deepcopy(session)

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        return deepcopy(self.sessions.get(session_id))

    def transition_session(self, session_id: int, target: ExtractionStage, actor: str, error: str | None = None) -> dict[str, Any]:
        session = self.sessions[session_id]
        validate_transition(ExtractionStage(session["stage"]), target)
        session.update(stage=target.value, error_message=error)
        self.audit.append({"action": "STAGE_TRANSITION", "actor": actor, "stage": target.value})
        return deepcopy(session)

    def load_document(self, document_id: int) -> dict[str, Any] | None:
        return deepcopy(self.documents.get(document_id))

    def save_candidates(self, session_id, entities, relationships, evidence, actor) -> None:
        for index, entity in enumerate(entities, 1):
            self.entities.append({"id": index, "session_id": session_id, "kind": "ENTITY", "name": entity.name, "entity_type": entity.entity_type, "confidence": entity.confidence, "review_status": "PENDING"})
        for index, (relationship, proof) in enumerate(zip(relationships, evidence, strict=True), 1):
            evidence_id = index
            self.evidence[evidence_id] = {"id": evidence_id, "session_id": session_id, "exact_text": proof.exact_text, "source_sha256": proof.source_sha256, "provenance": proof.provenance}
            self.relationships.append({"id": 100 + index, "session_id": session_id, "kind": "RELATIONSHIP", "predicate": relationship.predicate, "evidence_id": evidence_id, "review_status": "PENDING"})
        self.audit.append({"action": "CANDIDATES_SAVED", "actor": actor})

    def get_evidence(self, evidence_id: int) -> dict[str, Any] | None:
        return deepcopy(self.evidence.get(evidence_id))

    def get_candidates(self, session_id: int) -> dict[str, Any] | None:
        if session_id not in self.sessions:
            return None
        return {"session_id": session_id, "entities": deepcopy(self.entities), "relationships": deepcopy(self.relationships), "canonical_graph_mutated": False}

    def update_candidate(self, candidate_id: int, changes: dict[str, Any], actor: str, reason: str) -> dict[str, Any] | None:
        candidates = self.entities + self.relationships
        candidate = next((item for item in candidates if item["id"] == candidate_id), None)
        if candidate is None:
            return None
        previous = deepcopy(candidate)
        candidate.update(changes)
        self.audit.append({"action": "CANDIDATE_MODIFIED", "actor": actor, "reason": reason, "previous": previous})
        return deepcopy(candidate)


class MemoryReviewRepository:
    def __init__(self, candidates: MemoryRepository) -> None:
        self.candidates = candidates

    def record_review(self, session_id, candidate_ids, decision, actor, notes):
        if session_id not in self.candidates.sessions:
            raise LookupError("SESSION_NOT_FOUND")
        all_ids = {item["id"] for item in self.candidates.entities + self.candidates.relationships}
        if not set(candidate_ids) <= all_ids:
            raise ValueError("CANDIDATE_SESSION_MISMATCH")
        self.candidates.audit.append({"action": "REVIEW_RECORDED", "actor": actor})
        return {"id": 1, "session_id": session_id, "decision": decision, "candidate_ids": list(candidate_ids), "notes": notes, "canonical_graph_mutated": False}


def build_client(repository: MemoryRepository) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    review = MemoryReviewRepository(repository)
    app.dependency_overrides[get_candidate_repository] = lambda: repository
    app.dependency_overrides[get_review_repository] = lambda: review
    app.dependency_overrides[get_extraction_service] = lambda: ExtractionOrchestrationService(repository, RuleBasedSemanticExtractor())
    from app.security import verify_owner_or_api_key
    from app.routers.health import add_mission_control_cors_headers
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    return TestClient(app)


def test_state_machine_accepts_only_declared_sequence() -> None:
    validate_transition(ExtractionStage.QUEUED, ExtractionStage.PARSING)
    validate_transition(ExtractionStage.PARSING, ExtractionStage.FAILED)
    with pytest.raises(ValueError, match="INVALID_EXTRACTION_TRANSITION"):
        validate_transition(ExtractionStage.QUEUED, ExtractionStage.READY_FOR_REVIEW)
    assert not STAGE_TRANSITIONS[ExtractionStage.READY_FOR_REVIEW]


def test_rule_extractor_builds_entities_relationship_and_exact_evidence() -> None:
    text = "Dracula lafleurii is pollinated by Euglossa."
    extractor = RuleBasedSemanticExtractor()
    entities = extractor.extract_entities(text)
    relationships = extractor.extract_relationships(text, entities)
    evidence = extractor.build_evidence(text, "b" * 64, relationships, 11)
    assert [item.name for item in entities] == ["Dracula lafleurii", "Euglossa"]
    assert relationships[0].predicate == "POLLINATED_BY"
    assert evidence == [EvidenceDraft("TEXT_SPAN", text[:-1], 0, len(text) - 1, "b" * 64, {"document_id": 11, "extractor": "rule-based-v1", "content_sha256": "b" * 64})]


def test_orchestration_end_to_end_is_review_only_and_audited() -> None:
    repository = MemoryRepository()
    result = ExtractionOrchestrationService(repository, RuleBasedSemanticExtractor()).extract(7, "owner")
    assert result["stage"] == "READY_FOR_REVIEW"
    assert repository.relationships[0]["evidence_id"] in repository.evidence
    assert repository.evidence[1]["provenance"]["document_id"] == 7
    assert [event["stage"] for event in repository.audit if "stage" in event] == [
        "PARSING", "ENTITY_EXTRACTION", "RELATIONSHIP_EXTRACTION", "EVIDENCE_GENERATION", "CANDIDATE_GENERATION", "READY_FOR_REVIEW"
    ]
    assert not hasattr(repository, "publish")


def test_orchestration_records_failed_terminal_state() -> None:
    repository = MemoryRepository()
    repository.documents[7]["extracted_text"] = ""
    with pytest.raises(ValueError, match="DOCUMENT_TEXT_NOT_AVAILABLE"):
        ExtractionOrchestrationService(repository, RuleBasedSemanticExtractor()).extract(7, "owner")
    assert repository.sessions[1]["stage"] == "FAILED"
    assert repository.sessions[1]["error_message"] == "DOCUMENT_TEXT_NOT_AVAILABLE"


def test_candidate_change_filter_and_schema_require_real_modification() -> None:
    assert candidate_changes({"actor": "a", "reason": "r", "confidence": 0.7}) == {"confidence": 0.7}
    with pytest.raises(ValueError, match="NO_CANDIDATE_CHANGES"):
        candidate_changes({"actor": "a"})
    with pytest.raises(ValueError):
        CandidatePatch(actor="owner", reason="correction")


def test_repository_configuration_requires_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        semantic_database_url()
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://semantic-test")
    assert semantic_database_url() == "postgresql://semantic-test"


def test_migration_enforces_evidence_immutability_and_graph_isolation() -> None:
    sql = Path("migrations/076b_semantic_extraction.sql").read_text(encoding="utf-8")
    assert "semantic_evidence_immutable" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "evidence_id BIGINT NOT NULL" in sql
    assert "canonical_promotion_prohibited BOOLEAN NOT NULL DEFAULT TRUE" in sql
    assert "oc_graph" not in sql and "knowledge_graph" not in sql


def test_all_semantic_api_routes_and_end_to_end_workflow() -> None:
    repository = MemoryRepository()
    client = build_client(repository)
    extracted = client.post("/semantic/extract", json={"document_id": 7, "actor": "owner"})
    assert extracted.status_code == 201
    assert extracted.json()["stage"] == "READY_FOR_REVIEW"
    assert extracted.json()["canonical_graph_mutated"] is False
    assert client.get("/semantic/session/1").status_code == 200
    proof = client.get("/semantic/evidence/1")
    assert proof.status_code == 200 and proof.json()["source_sha256"] == "a" * 64
    candidates = client.get("/semantic/candidates/1")
    assert candidates.status_code == 200
    relationship = candidates.json()["relationships"][0]
    assert relationship["evidence_id"] == 1
    patched = client.patch("/semantic/candidate/1", json={"actor": "owner", "reason": "type correction", "entity_type": "SPECIES"})
    assert patched.status_code == 200 and patched.json()["entity_type"] == "SPECIES"
    reviewed = client.post("/semantic/review", json={"session_id": 1, "candidate_ids": [1, relationship["id"]], "decision": "ACCEPT", "actor": "owner"})
    assert reviewed.status_code == 201
    assert reviewed.json()["canonical_graph_mutated"] is False
    assert any(event["action"] == "CANDIDATE_MODIFIED" for event in repository.audit)
    assert any(event["action"] == "REVIEW_RECORDED" for event in repository.audit)


def test_api_returns_stable_not_found_and_validation_errors() -> None:
    repository = MemoryRepository()
    client = build_client(repository)
    assert client.get("/semantic/session/99").status_code == 404
    assert client.get("/semantic/evidence/99").status_code == 404
    assert client.get("/semantic/candidates/99").status_code == 404
    assert client.patch("/semantic/candidate/99", json={"actor": "owner", "reason": "fix", "confidence": 0.5}).status_code == 404
    assert client.post("/semantic/extract", json={"document_id": 999, "actor": "owner"}).status_code == 404


def test_router_registers_exact_build_076b_contract() -> None:
    routes = {(route.path, next(iter(route.methods))) for route in router.routes}
    assert ("/semantic/extract", "POST") in routes
    assert ("/semantic/session/{session_id}", "GET") in routes
    assert ("/semantic/evidence/{evidence_id}", "GET") in routes
    assert ("/semantic/candidates/{session_id}", "GET") in routes
    assert ("/semantic/candidate/{candidate_id}", "PATCH") in routes
    assert ("/semantic/review", "POST") in routes
