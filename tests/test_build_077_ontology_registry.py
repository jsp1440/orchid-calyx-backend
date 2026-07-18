from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ontology.dependencies import get_evidence_service, get_readiness_service, get_registry_service, get_resolution_service, get_term_service
from app.ontology.normalizers import normalize_canonical_key, normalize_ontology_text
from app.ontology.repositories import PostgresOntologyRepository
from app.ontology.routers import router
from app.ontology.services import CandidateResolutionService, DeterministicResolutionEngine, EvidenceRegistryService, OntologyRegistryService, OntologyTermService, PublicationReadinessService
from app.ontology.validators import ensure_no_hierarchy_cycle, require_provenance, validate_readiness_flags, validate_resolution_state


class FakeSearchCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.rows = [
            {
                "id": 1,
                "registry_id": 7,
                "canonical_key": "dracula_lafleurii",
                "preferred_label": "Dracula lafleurii",
                "normalized_label": "dracula lafleurii",
                "term_type": "TAXON",
                "namespace": "orchid-taxonomy",
                "version": "2026.1",
                "registry_status": "ACTIVE",
                "synonym": None,
                "normalized_synonym": None,
            }
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))

    def fetchall(self):
        return self.rows


class FakeSearchConnection:
    def __init__(self, cursor: FakeSearchCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class MemoryOntologyRepository:
    def __init__(self) -> None:
        self.registries: dict[int, dict[str, Any]] = {}
        self.terms: dict[int, dict[str, Any]] = {}
        self.synonyms: list[dict[str, Any]] = []
        self.resolutions: dict[int, dict[str, Any]] = {}
        self.evidence_entries: dict[int, dict[str, Any]] = {}
        self.readiness: dict[int, dict[str, Any]] = {}
        self.audit: list[str] = []
        self.candidates = {
            1: {"id": 1, "kind": "ENTITY", "name": "Dracula lafleurii", "review_status": "ACCEPTED", "session_id": 1},
            2: {"id": 2, "kind": "ENTITY", "name": "Euglossa", "review_status": "ACCEPTED", "session_id": 1},
            3: {"id": 3, "kind": "RELATIONSHIP", "review_status": "ACCEPTED", "session_id": 1, "evidence_id": 8},
        }
        self.contexts = {
            1: {"id": 1, "kind": "ENTITY", "candidate_review_status": "ACCEPTED", "session_stage": "READY_FOR_REVIEW", "candidate_provenance": {"document_id": 7}, "resolution_id": 1, "resolution_status": "ACCEPTED", "registry_status": "ACTIVE", "evidence_id": None, "evidence_validation_status": None, "subject_ready": False, "object_ready": False},
            2: {"id": 2, "kind": "ENTITY", "candidate_review_status": "ACCEPTED", "session_stage": "READY_FOR_REVIEW", "candidate_provenance": {"document_id": 7}, "resolution_id": 2, "resolution_status": "ACCEPTED", "registry_status": "ACTIVE", "evidence_id": None, "evidence_validation_status": None, "subject_ready": False, "object_ready": False},
            3: {"id": 3, "kind": "RELATIONSHIP", "candidate_review_status": "ACCEPTED", "session_stage": "READY_FOR_REVIEW", "candidate_provenance": {"document_id": 7}, "resolution_id": None, "resolution_status": None, "registry_status": None, "evidence_id": 8, "evidence_validation_status": "VALID", "subject_ready": True, "object_ready": True},
        }
        self.evidence_source_row = {"id": 8, "exact_text": "Dracula lafleurii is pollinated by Euglossa", "start_offset": 0, "end_offset": 44, "source_sha256": "a" * 64, "document_sha256": "a" * 64, "document_id": 7, "provenance": {"document_id": 7}}

    def create_registry(self, data, actor):
        if any(item["namespace"] == data["namespace"] and item["version"] == data["version"] for item in self.registries.values()): raise ValueError("DUPLICATE_REGISTRY_VERSION")
        row = {**data, "id": len(self.registries) + 1, "status": "DRAFT"}; self.registries[row["id"]] = row; self.audit.append("REGISTRY_CREATED"); return deepcopy(row)

    def update_registry(self, registry_id, changes, actor, reason):
        row = self.registries.get(registry_id)
        if row is None: return None
        if row["status"] != "DRAFT": raise ValueError("REGISTRY_IDENTITY_LOCKED")
        row.update(changes); self.audit.append("REGISTRY_UPDATED"); return deepcopy(row)

    def set_registry_status(self, registry_id, status, actor, reason):
        row = self.registries.get(registry_id)
        if row is None: return None
        row["status"] = status; self.audit.append(f"REGISTRY_{status}"); return deepcopy(row)

    def list_registries(self): return list(deepcopy(self.registries).values())
    def get_registry(self, registry_id): return deepcopy(self.registries.get(registry_id))

    def create_term(self, data, actor):
        if any(item["registry_id"] == data["registry_id"] and item["canonical_key"] == data["canonical_key"] for item in self.terms.values()): raise ValueError("DUPLICATE_CANONICAL_KEY")
        row = {**data, "id": len(self.terms) + 1, "status": "DRAFT", "namespace": self.registries[data["registry_id"]]["namespace"], "version": self.registries[data["registry_id"]]["version"]}; self.terms[row["id"]] = row; self.audit.append("TERM_CREATED"); return deepcopy(row)

    def update_term(self, term_id, changes, actor, reason):
        row = self.terms.get(term_id)
        if row is None: return None
        row.update(changes); self.audit.append("TERM_UPDATED"); return deepcopy(row)

    def get_term(self, term_id): return deepcopy(self.terms.get(term_id))

    def add_synonym(self, term_id, data, actor):
        if any(item["term_id"] == term_id and item["normalized_synonym"] == data["normalized_synonym"] and item["synonym_type"] == data["synonym_type"] for item in self.synonyms): raise ValueError("DUPLICATE_NORMALIZED_SYNONYM")
        row = {**data, "id": len(self.synonyms) + 1, "term_id": term_id}; self.synonyms.append(row); self.audit.append("SYNONYM_CREATED"); return deepcopy(row)

    def search_terms(self, query, registry_id=None):
        results = []
        for term in self.terms.values():
            registry = self.registries[term["registry_id"]]
            if registry["status"] != "ACTIVE" or (registry_id and term["registry_id"] != registry_id): continue
            matches = [item for item in self.synonyms if item["term_id"] == term["id"]] or [None]
            for synonym in matches: results.append({**term, "synonym": synonym["synonym"] if synonym else None, "normalized_synonym": synonym["normalized_synonym"] if synonym else None})
        return results

    def hierarchy_ancestors(self, term_id):
        ancestors=[]
        while term_id:
            ancestors.append(term_id); term_id=self.terms.get(term_id, {}).get("parent_term_id")
        return ancestors

    def get_entity_candidate(self, candidate_id):
        row=self.candidates.get(candidate_id); return deepcopy(row) if row and row["kind"] == "ENTITY" else None
    def get_session_entity_candidates(self, session_id): return [deepcopy(row) for row in self.candidates.values() if row["session_id"] == session_id and row["kind"] == "ENTITY"]

    def create_resolution(self, candidate_id, suggestion, actor):
        row={**suggestion, "id": len(self.resolutions)+1, "candidate_id": candidate_id}; self.resolutions[row["id"]]=row; self.audit.append("RESOLUTION_PROPOSED"); return deepcopy(row)
    def list_resolutions(self, candidate_id): return [deepcopy(row) for row in self.resolutions.values() if row["candidate_id"] == candidate_id]
    def decide_resolution(self, resolution_id, status, actor, reason):
        row=self.resolutions.get(resolution_id)
        if row is None:return None
        if status == "ACCEPTED" and any(item["candidate_id"] == row["candidate_id"] and item["status"] == "ACCEPTED" and item["id"] != resolution_id for item in self.resolutions.values()): raise ValueError("MULTIPLE_ACCEPTED_RESOLUTIONS")
        row["status"]=status; row["resolved_by"]=actor; self.audit.append("RESOLUTION_DECIDED"); return deepcopy(row)

    def evidence_source(self, evidence_object_id): return deepcopy(self.evidence_source_row) if evidence_object_id == 8 else None
    def create_evidence_entry(self, evidence_object_id, data, actor):
        if evidence_object_id in self.evidence_entries: raise ValueError("DUPLICATE_EVIDENCE_ENTRY")
        row={**data,"id":1,"evidence_object_id":evidence_object_id}; self.evidence_entries[evidence_object_id]=row; self.audit.append("EVIDENCE_REGISTERED"); return deepcopy(row)
    def get_evidence_entry(self, evidence_object_id): return deepcopy(self.evidence_entries.get(evidence_object_id))
    def validate_evidence_entry(self, evidence_object_id, status, details, actor):
        row=self.evidence_entries.get(evidence_object_id)
        if row is None:return None
        row.update(validation_status=status,validation_details=dict(details)); self.audit.append("EVIDENCE_VALIDATED"); return deepcopy(row)

    def readiness_context(self, candidate_id): return deepcopy(self.contexts.get(candidate_id))
    def session_candidate_ids(self, session_id): return [item["id"] for item in self.candidates.values() if item["session_id"] == session_id]
    def save_readiness(self, candidate_id, result, actor):
        row={**result,"id":len(self.readiness)+1,"candidate_id":candidate_id,"canonical_graph_mutated":False}; self.readiness[candidate_id]=row; self.audit.append("READINESS_EVALUATED"); return deepcopy(row)
    def get_readiness(self, candidate_id): return deepcopy(self.readiness.get(candidate_id))


@pytest.fixture
def repository(): return MemoryOntologyRepository()


@pytest.fixture
def seeded(repository):
    registry = OntologyRegistryService(repository).create_registry({"namespace":"orchid-taxonomy","name":"Orchid Names","authority":"Example Herbarium","source_uri":None,"version":"2026.1","ontology_type":"TAXONOMY","checksum":"a"*64,"provenance":{"source":"curated release"},"created_by":"owner"})
    term = OntologyTermService(repository).create_term({"registry_id":registry["id"],"canonical_key":"dracula_lafleurii","preferred_label":"Dracula lafleurii","term_type":"TAXON","actor":"owner"})
    OntologyRegistryService(repository).activate_registry(registry["id"],"owner","reviewed release")
    return registry, term


def test_normalization_is_unicode_whitespace_case_and_scientific_safe():
    assert normalize_ontology_text("  DRACULA\u00a0lafleurii. ", scientific_name=True) == "dracula lafleurii"
    assert normalize_ontology_text("Phalaenopsis x hybrid", scientific_name=True) == "phalaenopsis × hybrid"
    assert normalize_canonical_key(" Orchid Species ") == "orchid_species"


def test_registry_creation_version_uniqueness_activation_and_deprecation(repository):
    service=OntologyRegistryService(repository); data={"namespace":"tax","name":"Tax","authority":"Herbarium","version":"1","ontology_type":"TAXONOMY","checksum":"a"*64,"provenance":{"release":"1"},"created_by":"owner"}
    registry=service.create_registry(data)
    with pytest.raises(ValueError,match="DUPLICATE"): service.create_registry(data)
    assert service.activate_registry(registry["id"],"owner","approved")["status"] == "ACTIVE"
    assert service.deprecate_registry(registry["id"],"owner","new version")["status"] == "DEPRECATED"
    with pytest.raises(ValueError,match="LOCKED"): service.update_draft_registry(registry["id"],{"name":"changed"},"owner","no")


def test_term_creation_duplicate_synonym_resolution_and_search(repository, seeded):
    registry,term=seeded; service=OntologyTermService(repository)
    synonym=service.add_synonym(term["id"],{"synonym":"Dracula lafleurii Luer","synonym_type":"SCIENTIFIC_NAME","provenance":{"publication":"protologue"},"actor":"owner"})
    assert synonym["normalized_synonym"] == "dracula lafleurii luer"
    with pytest.raises(ValueError,match="DUPLICATE"): service.add_synonym(term["id"],{"synonym":"DRACULA LAFLEURII LUER","synonym_type":"SCIENTIFIC_NAME","provenance":{"publication":"same"},"actor":"owner"})
    assert service.search_terms("Dracula",registry["id"])


def test_hierarchy_cycles_and_replacement_links_rejected(repository, seeded):
    registry,parent=seeded; registry["status"]="DRAFT"; repository.registries[registry["id"]]["status"]="DRAFT"
    child=OntologyTermService(repository).create_term({"registry_id":registry["id"],"canonical_key":"child","preferred_label":"Child","term_type":"TAXON","parent_term_id":parent["id"],"actor":"owner"})
    with pytest.raises(ValueError,match="CYCLE"): OntologyTermService(repository).update_draft_term(parent["id"],{"parent_term_id":child["id"]},"owner","cycle")
    with pytest.raises(ValueError,match="SELF_REPLACEMENT"): OntologyTermService(repository).deprecate_term(parent["id"],parent["id"],"owner","invalid")


def test_exact_normalized_synonym_and_fuzzy_resolution_never_auto_accept(repository, seeded):
    registry,term=seeded; OntologyTermService(repository).add_synonym(term["id"],{"synonym":"D. lafleurii","synonym_type":"ABBREVIATION","provenance":{"source":"index"},"actor":"owner"})
    terms=repository.search_terms("")
    engine=DeterministicResolutionEngine(.8)
    assert engine.suggestions("Dracula lafleurii",terms)[0]["resolution_method"] == "EXACT"
    assert engine.suggestions("DRACULA LAFLEURII.",terms)[0]["resolution_method"] == "NORMALIZED"
    assert engine.suggestions("D. lafleurii",terms)[0]["resolution_method"] == "SYNONYM"
    fuzzy=engine.suggestions("Dracula lafleur",terms)[0]
    assert fuzzy["resolution_method"] == "FUZZY" and fuzzy["status"] == "PROPOSED"


def test_resolution_service_exact_and_normalized_paths(repository, seeded):
    service=CandidateResolutionService(repository)
    exact=service.resolve_one(1,"owner")[0]
    assert exact["resolution_method"] == "EXACT"
    assert exact["status"] == "PROPOSED"

    repository.candidates[1]["name"]="DRACULA LAFLEURII."
    normalized=service.resolve_one(1,"owner")[0]
    assert normalized["resolution_method"] == "NORMALIZED"
    assert normalized["status"] == "PROPOSED"


def test_postgres_search_terms_empty_and_non_empty_queries_have_typed_optional_registry_filter(monkeypatch):
    cursor=FakeSearchCursor()
    repository=PostgresOntologyRepository("postgresql://build-077-validation")
    monkeypatch.setattr(repository, "_connect", lambda: FakeSearchConnection(cursor))

    assert repository.search_terms("")
    assert repository.search_terms("dracula", registry_id=7)

    empty_sql, empty_params=cursor.calls[0]
    filtered_sql, filtered_params=cursor.calls[1]
    assert "%s::bigint IS NULL OR t.registry_id=%s::bigint" in empty_sql
    assert "%s::bigint IS NULL OR t.registry_id=%s::bigint" in filtered_sql
    assert empty_params == (None, None)
    assert filtered_params == (7, 7)


def test_unresolved_manual_accept_reject_and_duplicate_acceptance(repository, seeded):
    service=CandidateResolutionService(repository)
    repository.candidates[1]["name"]="No matching concept"
    unresolved=service.resolve_one(1,"owner")[0]
    assert unresolved["resolution_method"] == "UNRESOLVED" and unresolved["ontology_term_id"] is None
    manual=service.manual_assign(1,seeded[1]["id"],"owner","curator assignment")
    assert manual["status"] == "PROPOSED"
    accepted=service.decide(manual["id"],"ACCEPTED","owner","verified")
    assert accepted["status"] == "ACCEPTED"
    second=service.manual_assign(1,seeded[1]["id"],"owner","second")
    with pytest.raises(ValueError,match="MULTIPLE_ACCEPTED"): service.decide(second["id"],"ACCEPTED","owner","conflict")
    assert service.decide(second["id"],"REJECTED","owner","duplicate")["status"] == "REJECTED"


def test_evidence_registration_hash_validation_and_original_immutability(repository):
    service=EvidenceRegistryService(repository); original=deepcopy(repository.evidence_source_row)
    entry=service.register(8,"owner")
    assert entry["validation_status"] == "PENDING"
    assert service.validate(8,"owner")["validation_status"] == "VALID"
    assert repository.evidence_source_row == original
    repository.evidence_source_row["document_sha256"]="b"*64
    assert service.revalidate(8,"owner")["validation_details"]["failures"] == ["DOCUMENT_SOURCE_HASH_MISMATCH"]


@pytest.mark.parametrize(("change","blocker"),[
    ({"candidate_review_status":"PENDING"},"CANDIDATE_NOT_ACCEPTED"),({"session_stage":"FAILED"},"SESSION_NOT_READY_FOR_REVIEW"),
    ({"candidate_provenance":{}},"PROVENANCE_INCOMPLETE"),({"resolution_id":None},"ONTOLOGY_UNRESOLVED"),
    ({"resolution_status":"PROPOSED"},"ONTOLOGY_MATCH_NOT_ACCEPTED"),({"registry_status":"DEPRECATED"},"ONTOLOGY_VERSION_INACTIVE")])
def test_every_entity_readiness_blocker(repository,change,blocker):
    repository.contexts[1].update(change)
    assert blocker in PublicationReadinessService(repository).evaluate_candidate(1,"owner")["blockers"]


@pytest.mark.parametrize(("change","blocker"),[
    ({"evidence_id":None},"EVIDENCE_MISSING"),({"evidence_validation_status":"INVALID"},"EVIDENCE_INVALID"),
    ({"subject_ready":False},"SUBJECT_NOT_READY"),({"object_ready":False},"OBJECT_NOT_READY")])
def test_every_relationship_readiness_blocker(repository,change,blocker):
    repository.contexts[3].update(change)
    assert blocker in PublicationReadinessService(repository).evaluate_candidate(3,"owner")["blockers"]


def test_readiness_success_relationship_dependencies_and_session(repository):
    service=PublicationReadinessService(repository)
    assert service.evaluate_candidate(1,"owner")["ready_for_publication"] is True
    assert service.evaluate_candidate(2,"owner")["ready_for_publication"] is True
    assert service.evaluate_candidate(3,"owner")["ready_for_publication"] is True
    assert service.evaluate_session(1,"owner")["ready_for_publication"] is True
    validate_readiness_flags({"evidence_complete":True,"ontology_resolved":True,"review_complete":True,"provenance_complete":True,"ready_for_publication":True},[])


def test_validators_reject_inconsistent_states():
    with pytest.raises(ValueError,match="PROVENANCE"): require_provenance({})
    with pytest.raises(ValueError,match="UNRESOLVED_WITH_TERM"): validate_resolution_state("UNRESOLVED","NEEDS_REVIEW",1)
    with pytest.raises(ValueError,match="REQUIRES_TERM"): validate_resolution_state("MANUAL","ACCEPTED",None)
    with pytest.raises(ValueError,match="INVALID_READINESS"): validate_readiness_flags({"ready_for_publication":True},["EVIDENCE_MISSING"])
    with pytest.raises(ValueError,match="SELF_PARENT"): ensure_no_hierarchy_cycle(1,1,[])


def test_migration_is_additive_rerunnable_immutable_and_graph_isolated():
    sql=Path("migrations/077_ontology_evidence_registry.sql").read_text(encoding="utf-8").lower()
    assert "create schema if not exists oc_ontology" in sql and sql.count("create table if not exists") >= 7
    assert "ontology_evidence_hash_immutable" in sql and "ontology_one_accepted_resolution_idx" in sql
    assert "drop table" not in sql and "truncate" not in sql and "delete from" not in sql
    assert "oc_graph" not in sql and "canonical_taxonomy" not in sql


def test_build_076b_evidence_and_routes_remain_unchanged():
    semantic=Path("app/semantic/repositories.py").read_text(encoding="utf-8")
    assert "UPDATE oc_semantic.evidence_objects" not in semantic
    paths={route.path for route in router.routes}
    assert "/api/ontology/readiness/candidate/{candidate_id}" in paths
    assert not any("publish" in path for path in paths)


def test_audit_events_created_for_every_mutation(repository, seeded):
    OntologyTermService(repository).add_synonym(seeded[1]["id"],{"synonym":"D. lafleurii","synonym_type":"ABBREVIATION","provenance":{"source":"x"},"actor":"owner"})
    CandidateResolutionService(repository).resolve_one(1,"owner")
    EvidenceRegistryService(repository).register(8,"owner")
    EvidenceRegistryService(repository).validate(8,"owner")
    PublicationReadinessService(repository).evaluate_candidate(1,"owner")
    assert {"REGISTRY_CREATED","TERM_CREATED","REGISTRY_ACTIVE","SYNONYM_CREATED","RESOLUTION_PROPOSED","EVIDENCE_REGISTERED","EVIDENCE_VALIDATED","READINESS_EVALUATED"} <= set(repository.audit)


def test_api_authentication_and_error_contract(repository):
    app=FastAPI(); app.include_router(router); client=TestClient(app)
    response=client.get("/api/ontology/registries")
    assert response.status_code in {401,503}


def test_api_happy_path_with_owner_dependency_overrides(repository):
    registry_service=OntologyRegistryService(repository); term_service=OntologyTermService(repository)
    app=FastAPI(); app.include_router(router)
    from app.security import verify_owner_or_api_key
    from app.routers.health import add_mission_control_cors_headers
    app.dependency_overrides[verify_owner_or_api_key]=lambda:{"actor":"owner"}; app.dependency_overrides[add_mission_control_cors_headers]=lambda:None
    app.dependency_overrides[get_registry_service]=lambda:registry_service; app.dependency_overrides[get_term_service]=lambda:term_service
    app.dependency_overrides[get_resolution_service]=lambda:CandidateResolutionService(repository); app.dependency_overrides[get_evidence_service]=lambda:EvidenceRegistryService(repository); app.dependency_overrides[get_readiness_service]=lambda:PublicationReadinessService(repository)
    client=TestClient(app)
    created=client.post("/api/ontology/registries",json={"namespace":"tax","name":"Tax","authority":"Herbarium","version":"1","ontology_type":"TAXONOMY","checksum":"a"*64,"provenance":{"source":"release"},"created_by":"owner"})
    assert created.status_code==201
    term=client.post("/api/ontology/terms",json={"registry_id":created.json()["id"],"canonical_key":"dracula_lafleurii","preferred_label":"Dracula lafleurii","term_type":"TAXON","actor":"owner"})
    assert term.status_code==201
    assert client.post(f"/api/ontology/registries/{created.json()['id']}/activate",json={"actor":"owner","reason":"reviewed"}).status_code==200
    assert client.post("/api/ontology/resolve/candidate/1",json={"actor":"owner"}).status_code==201
    assert client.post("/api/ontology/evidence/register/8",json={"actor":"owner"}).status_code==201
    assert client.post("/api/ontology/evidence/8/validate",json={"actor":"owner"}).json()["validation_status"]=="VALID"
    assert client.post("/api/ontology/readiness/candidate/1",json={"actor":"owner"}).status_code==200
    assert client.get("/api/ontology/terms/999").status_code==404
