import concurrent.futures,os
from pathlib import Path
import pytest
from fastapi import HTTPException
from app.candidate_knowledge.models import EvidenceInput,SourceAnchor
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.evidence_aggregation.models import CandidateInput
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService
from app.persistence.state_repository import decode,encode

DSN=os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
db=pytest.mark.skipif(not DSN,reason="no disposable PostgreSQL validation database")

def evidence(i=1):return EvidenceInput("CLAIM",i,i,i,"source evidence",(SourceAnchor(i,locator={"page":1}),),display_policy="METADATA_ONLY",metadata={"candidate_facts":[{"kind":"TRAIT","subject":"Taxon","predicate":"has_trait","object_value":"green"}]})
def candidate(i=1):return CandidateInput(i,1,"TRAIT","taxon","has_trait",object_value="green",source_revision_id=i,source_document_id=f"doc-{i}",source_anchor_ids=(i,),source_lineage=f"study-{i}",document_hash=f"hash-{i}")

def test_additive_migration_and_protected_schema_safety():
 sql=Path("migrations/086d_persistent_runtime.sql").read_text().upper();assert "CREATE SCHEMA IF NOT EXISTS OC_CANDIDATE_KNOWLEDGE" in sql and "RUNTIME_REPOSITORY_SNAPSHOTS" in sql and "PG_ADVISORY" not in sql
 assert all(x not in sql for x in ("DROP ","TRUNCATE ","OC_GRAPH.","OC_TAXONOMY."))

def test_state_codec_round_trip_preserves_dataclasses_tuple_keys_and_anchors():
 value={1:{"evidence":evidence(),"candidate":candidate(),"key":("topic",1)}};decoded=decode(encode(value));assert decoded[1]["evidence"]==evidence() and decoded[1]["candidate"]==candidate() and decoded[1]["key"]==("topic",1)

@db
def test_postgres_candidate_persistence_restart_resume_rollback_and_lock_cleanup():
 import psycopg
 from app.candidate_knowledge.postgres_repository import PostgresCandidateRepository
 with psycopg.connect(DSN) as conn:conn.execute(Path("migrations/086d_persistent_runtime.sql").read_text())
 repo=PostgresCandidateRepository(DSN);service=CandidateExtractionService(repo);plan=repo.atomic(lambda:service.preview([evidence()]));repo.atomic(lambda:service.cancel(plan["candidate_run_id"]));fresh=PostgresCandidateRepository(DSN);assert fresh.runs[plan["candidate_run_id"]]["state"]=="CANCELLING";fresh_service=CandidateExtractionService(fresh);fresh.atomic(lambda:fresh_service.resume(plan["candidate_run_id"]));assert PostgresCandidateRepository(DSN).candidates
 before=len(PostgresCandidateRepository(DSN).candidates)
 def fail():fresh.candidates.append({"candidate_id":999});raise RuntimeError("controlled failure")
 with pytest.raises(RuntimeError):fresh.atomic(fail)
 assert len(PostgresCandidateRepository(DSN).candidates)==before and fresh.lock_available()

@db
def test_postgres_aggregate_persistence_concurrent_idempotency_and_restart():
 import psycopg
 from app.evidence_aggregation.postgres_repository import PostgresAggregateRepository
 with psycopg.connect(DSN) as conn:conn.execute(Path("migrations/086d_persistent_runtime.sql").read_text())
 def submit():
  repo=PostgresAggregateRepository(DSN);service=EvidenceAggregationService(repo)
  def operation():plan=service.preview([candidate()]);return service.execute(plan["aggregate_run_id"])
  return repo.atomic(operation)["state"]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:states=list(pool.map(lambda _:submit(),range(4)))
 fresh=PostgresAggregateRepository(DSN);assert all(x=="COMPLETED" for x in states) and len(fresh.versions)==1 and sum(x["active"] for x in fresh.versions)==1 and fresh.lock_available()

def test_candidate_pagination_order_filters_not_found_and_unavailable(monkeypatch):
 import app.candidate_knowledge.routes as routes
 repo=MemoryCandidateRepository();repo.candidates=[{"candidate_id":2,"version":1,"active":True,"kind":"TRAIT","review_state":"REQUIRED"},{"candidate_id":1,"version":1,"active":True,"kind":"TRAIT","review_state":"REQUIRED"}];monkeypatch.setattr(routes,"REPOSITORY",repo);monkeypatch.setattr(routes,"SERVICE",CandidateExtractionService(repo))
 page=routes.candidates(kind="TRAIT",limit=1,offset=0);assert page["total"]==2 and page["items"][0]["candidate_id"]==1
 with pytest.raises(HTTPException) as missing:routes.candidate(999)
 assert missing.value.status_code==404
 monkeypatch.setattr(routes,"REPOSITORY",None);monkeypatch.setattr(routes,"SERVICE",None)
 with pytest.raises(HTTPException) as unavailable:routes._read()
 assert unavailable.value.status_code==503

def test_aggregate_pagination_stable_order_filters_not_found_and_empty(monkeypatch):
 import app.evidence_aggregation.routes as routes
 repo=MemoryAggregateRepository();repo.versions=[{"aggregate_id":2,"version":1,"active":True,"aggregate_type":"TRAIT_AGGREGATE","aggregate_status":"SUPPORTED","review_state":"REQUIRED"},{"aggregate_id":1,"version":1,"active":True,"aggregate_type":"TRAIT_AGGREGATE","aggregate_status":"SUPPORTED","review_state":"REQUIRED"}];monkeypatch.setattr(routes,"REPOSITORY",repo);monkeypatch.setattr(routes,"SERVICE",EvidenceAggregationService(repo))
 page=routes.aggregates(aggregate_type="TRAIT_AGGREGATE",limit=1,offset=0);assert page["total"]==2 and page["items"][0]["aggregate_id"]==1
 assert routes.aggregates(aggregate_type="OTHER",limit=10,offset=0)["items"]==[]
 with pytest.raises(HTTPException) as missing:routes.aggregate(999)
 assert missing.value.status_code==404

def test_pagination_bounds_auth_and_malformed_json_are_framework_validated(monkeypatch):
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
 import app.evidence_aggregation.routes as routes
 from app.security import verify_owner_or_api_key
 repo=MemoryAggregateRepository();monkeypatch.setattr(routes,"REPOSITORY",repo);monkeypatch.setattr(routes,"SERVICE",EvidenceAggregationService(repo));app=FastAPI();app.include_router(routes.router);app.dependency_overrides[verify_owner_or_api_key]=lambda:{"actor":"test"};client=TestClient(app)
 assert client.get("/api/evidence-aggregation/aggregates?limit=0").status_code==422
 assert client.post("/api/evidence-aggregation/preview",content="{",headers={"content-type":"application/json"}).status_code==422
 app.dependency_overrides.clear();assert client.get("/api/evidence-aggregation/aggregates").status_code==401

def test_no_publication_drive_protected_schema_secret_or_file_surface():
 code="\n".join(p.read_text(errors="ignore") for folder in (Path("app/candidate_knowledge"),Path("app/evidence_aggregation"),Path("app/persistence")) for p in folder.glob("*.py"));assert all(x not in code for x in ("drive.files.update","drive.files.create","production_publish","publish_node","publish_edge","gho_","BEGIN PRIVATE KEY","../"))
 from app.candidate_knowledge.routes import router as a
 from app.evidence_aggregation.routes import router as b
 assert not any("publish" in route.path for route in [*a.routes,*b.routes])
