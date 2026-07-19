from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.publication.dependencies import get_publication_service
from app.publication.routers import router
from app.publication.services import PublicationService
from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key


class MemoryPublicationRepository:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, int, int, str], dict[str, Any]] = {}
        self.runs: dict[int, dict[str, Any]] = {}
        self.items: dict[int, list[dict[str, Any]]] = {}
        self.rollbacks: list[dict[str, Any]] = []
        self.next_run_id = 1
        self.next_item_id = 1
        self.next_node_id = 1
        self.next_edge_id = 1
        self.candidates = {
            1: self._entity(1, "TAXON", "Dracula lafleurii", {"canonical_taxon_id": "wp:123"}),
            2: self._entity(2, "POLLINATOR", "Euglossa imperialis", {}),
            3: self._relationship(3, 1, "associated_with_pollinator", 2, 8),
            4: self._entity(4, "TAXON", "Unsafe taxon", {}),
        }

    def _entity(self, candidate_id: int, term_type: str, name: str, external_ids: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": candidate_id,
            "session_id": 10,
            "kind": "ENTITY",
            "confidence": 0.98,
            "review_status": "ACCEPTED",
            "session_stage": "READY_FOR_REVIEW",
            "session_provenance": {"document_id": 70},
            "entity_type": term_type,
            "name": name,
            "ready_for_publication": True,
            "readiness_blockers": [],
            "resolution_id": candidate_id,
            "resolution_status": "ACCEPTED",
            "ontology_term_id": candidate_id,
            "resolution_method": "EXACT",
            "resolution_confidence": 1.0,
            "resolution_provenance": {"resolver": "test"},
            "term_canonical_key": name.lower().replace(" ", "_"),
            "preferred_label": name,
            "term_type": term_type,
            "external_ids": external_ids,
            "term_metadata": {},
            "term_status": "ACTIVE",
            "namespace": "orchid-taxonomy" if term_type == "TAXON" else "orchid-pollinators",
            "version": "2026.1",
            "registry_status": "ACTIVE",
            "ontology_type": "TAXONOMY" if term_type == "TAXON" else "POLLINATOR",
            "evidence_id": None,
        }

    def _relationship(self, candidate_id: int, subject_id: int, predicate: str, object_id: int, evidence_id: int) -> dict[str, Any]:
        return {
            "id": candidate_id,
            "session_id": 10,
            "kind": "RELATIONSHIP",
            "confidence": 0.91,
            "review_status": "ACCEPTED",
            "session_stage": "READY_FOR_REVIEW",
            "session_provenance": {"document_id": 70},
            "ready_for_publication": True,
            "readiness_blockers": [],
            "subject_candidate_id": subject_id,
            "predicate": predicate,
            "object_candidate_id": object_id,
            "evidence_id": evidence_id,
            "evidence_validation_status": "VALID",
            "evidence_hash": "a" * 64,
            "source_sha256": "a" * 64,
        }

    def candidate_ids_for_scope(self, scope: dict[str, Any]) -> list[int]:
        ids = [1, 2, 3] if scope.get("session_id") == 10 else list(scope.get("candidate_ids") or [])
        return sorted(ids, key=lambda item: (self.candidates[item]["kind"] == "RELATIONSHIP", item))

    def load_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        return deepcopy(self.candidates.get(candidate_id))

    def graph_counts(self) -> dict[str, int]:
        return {"nodes": len(self.nodes), "edges": len(self.edges)}

    def get_node_by_key(self, canonical_key: str) -> dict[str, Any] | None:
        return deepcopy(self.nodes.get(canonical_key))

    def existing_publication(self, mode: str, manifest_digest: str) -> dict[str, Any] | None:
        for run in self.runs.values():
            if run["mode"] == mode and run["manifest_digest"] == manifest_digest:
                return deepcopy(run)
        return None

    def read_run_items(self, run_id: int) -> list[dict[str, Any]]:
        return deepcopy(self.items[run_id])

    def record_dry_run(self, run: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
        return self._record("DRY_RUN", run, items, mutate=False)

    def publish(self, run: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
        return self._record("PUBLISH", run, items, mutate=True)

    def rollback_run(self, run_id: int, actor: str, reason: str, strategy: str) -> dict[str, Any]:
        run = self.runs[run_id]
        if run["status"] != "PUBLISHED":
            raise ValueError("ONLY_PUBLISHED_RUNS_CAN_BE_ROLLED_BACK")
        run["status"] = "ROLLED_BACK" if strategy == "MARK_ROLLED_BACK" else "SUPERSEDED"
        rollback = {"id": len(self.rollbacks) + 1, "run_id": run_id, "rollback_actor": actor, "reason": reason, "strategy": strategy, "canonical_graph_mutated": False, "run": deepcopy(run)}
        self.rollbacks.append(rollback)
        return deepcopy(rollback)

    def _record(self, mode: str, run: dict[str, Any], items: list[dict[str, Any]], mutate: bool) -> dict[str, Any]:
        stored_run = {
            "id": self.next_run_id,
            "mode": mode,
            "manifest_digest": run["manifest_digest"],
            "status": "PUBLISHED" if mutate else ("BLOCKED" if any(item["blockers"] for item in items) else "DRY_RUN_COMPLETE"),
            "canonical_graph_mutated": False,
            "item_count": len(items),
            "ready_count": sum(1 for item in items if item["state"] == "READY"),
            "blocked_count": sum(1 for item in items if item["state"] == "BLOCKED"),
            "inserted_node_count": 0,
            "linked_node_count": 0,
            "inserted_edge_count": 0,
            "linked_edge_count": 0,
        }
        self.next_run_id += 1
        stored_items = []
        for item in deepcopy(items):
            item["id"] = self.next_item_id
            item["run_id"] = stored_run["id"]
            self.next_item_id += 1
            if item["state"] == "BLOCKED":
                stored_items.append(item)
                continue
            if mutate and item["item_type"] == "ENTITY":
                existing = self.nodes.get(item["canonical_key"])
                if existing:
                    stored_run["linked_node_count"] += 1
                    item["graph_node_id"] = existing["kg_node_id"]
                else:
                    node = {"kg_node_id": self.next_node_id, "canonical_key": item["canonical_key"], "node_type": item["node_type"]}
                    self.next_node_id += 1
                    self.nodes[item["canonical_key"]] = node
                    stored_run["inserted_node_count"] += 1
                    item["graph_node_id"] = node["kg_node_id"]
                item["state"] = "PUBLISHED"
            elif mutate and item["item_type"] == "RELATIONSHIP":
                from_id = self.nodes[item["from_canonical_key"]]["kg_node_id"]
                to_id = self.nodes[item["to_canonical_key"]]["kg_node_id"]
                key = (item["edge_type"], from_id, to_id, "oc_semantic.candidate_relationships")
                if key in self.edges:
                    stored_run["linked_edge_count"] += 1
                    item["graph_edge_id"] = self.edges[key]["kg_edge_id"]
                else:
                    edge = {"kg_edge_id": self.next_edge_id, "edge_type": item["edge_type"]}
                    self.next_edge_id += 1
                    self.edges[key] = edge
                    stored_run["inserted_edge_count"] += 1
                    item["graph_edge_id"] = edge["kg_edge_id"]
                item["state"] = "PUBLISHED"
            else:
                item["state"] = "DRY_RUN_COMPLETE"
            stored_items.append(item)
        stored_run["canonical_graph_mutated"] = mutate and (stored_run["inserted_node_count"] > 0 or stored_run["inserted_edge_count"] > 0)
        self.runs[stored_run["id"]] = stored_run
        self.items[stored_run["id"]] = stored_items
        return {"run": deepcopy(stored_run), "items": deepcopy(stored_items)}


def request_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "actor": "owner",
        "reason": "release validation",
        "scope": {"session_id": 10},
        "approval_reference": "owner-approval-078",
        "publication_authority": "release-engineer",
    }
    payload.update(overrides)
    return payload


def test_dry_run_is_read_only_and_reports_deterministic_manifest():
    repository = MemoryPublicationRepository()
    service = PublicationService(repository)

    first = service.dry_run(request_payload())
    second = service.dry_run(request_payload())

    assert first["status"] == "DRY_RUN_COMPLETE"
    assert first["canonical_graph_mutated"] is False
    assert first["manifest_digest"] == second["manifest_digest"]
    assert repository.graph_counts() == {"nodes": 0, "edges": 0}


def test_taxonomy_publication_requires_canonical_taxon_attachment():
    service = PublicationService(MemoryPublicationRepository())

    result = service.dry_run(request_payload(scope={"candidate_ids": [4]}))

    assert result["status"] == "BLOCKED"
    assert result["blockers"][0]["blockers"] == ["CANONICAL_TAXON_ATTACHMENT_MISSING"]
    with pytest.raises(ValueError, match="PUBLICATION_BLOCKED"):
        service.publish(request_payload(scope={"candidate_ids": [4]}))


def test_publish_requires_human_approval_and_authority():
    service = PublicationService(MemoryPublicationRepository())

    with pytest.raises(ValueError, match="HUMAN_APPROVAL_REQUIRED"):
        service.publish(request_payload(approval_reference=None))
    with pytest.raises(ValueError, match="PUBLICATION_AUTHORITY_REQUIRED"):
        service.publish(request_payload(publication_authority=None))


def test_publish_is_idempotent_and_relationships_link_after_entity_nodes():
    repository = MemoryPublicationRepository()
    service = PublicationService(repository)

    first = service.publish(request_payload())
    second = service.publish(request_payload())

    assert first["status"] == "PUBLISHED"
    assert first["counts"]["inserted_nodes"] == 2
    assert first["counts"]["inserted_edges"] == 1
    assert second["run_id"] == first["run_id"]
    assert repository.graph_counts() == {"nodes": 2, "edges": 1}


def test_rollback_records_supersession_without_deleting_graph_records():
    repository = MemoryPublicationRepository()
    service = PublicationService(repository)
    published = service.publish(request_payload())

    rollback = service.rollback(published["run_id"], {"actor": "owner", "reason": "superseded", "strategy": "SUPERSEDE_ONLY"})

    assert rollback["run"]["status"] == "SUPERSEDED"
    assert rollback["canonical_graph_mutated"] is False
    assert repository.graph_counts() == {"nodes": 2, "edges": 1}


def test_publication_api_is_owner_or_api_key_protected():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    assert client.post("/api/publication/dry-run", json=request_payload()).status_code == 401


def test_publication_api_happy_path_with_dependency_override():
    repository = MemoryPublicationRepository()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner"}
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    app.dependency_overrides[get_publication_service] = lambda: PublicationService(repository)
    client = TestClient(app)

    response = client.post("/api/publication/dry-run", json=request_payload())

    assert response.status_code == 201
    assert response.json()["status"] == "DRY_RUN_COMPLETE"


def test_migration_is_additive_and_protects_publication_state_machine():
    sql = Path("migrations/078_controlled_publication_gate.sql").read_text(encoding="utf-8").lower()

    assert "create schema if not exists oc_publication" in sql
    assert sql.count("create table if not exists oc_publication.") >= 6
    assert "drop table" not in sql
    assert "alter table oc_graph" not in sql
    assert "alter table oc_taxonomy" not in sql
    assert "delete from oc_graph" not in sql
    assert "publication_item_state_transition_valid" in sql
    assert "publication_conflicts_open_idx" in sql
