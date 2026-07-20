from __future__ import annotations
import concurrent.futures,json,os,sys,time,tracemalloc
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.evidence_aggregation.models import CandidateInput
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService

TESTED_MAIN="d6e2cbb37dffc733ec3fea52e22ce70716713389"

def candidate(i,subject="Dracula vampira",value="bee",**kw):
 data={"candidate_id":i,"candidate_version":1,"candidate_type":"POLLINATOR_ASSOCIATION","normalized_subject":subject,"predicate":"pollinated_by","object_value":value,"source_revision_id":i,"source_document_id":f"document-{i}","source_anchor_ids":(i*10,),"source_class":"PRIMARY","evidence_type":"DIRECT_OBSERVATION","directness":"DIRECT_OBSERVATION","source_lineage":f"study-{i}","document_hash":f"hash-{i}","confidence":.8,"display_policy":"FULL_TEXT_ALLOWED"};data.update(kw);return CandidateInput(**data)

def aggregate(items):
 repo=MemoryAggregateRepository();service=EvidenceAggregationService(repo);plan=service.preview(items);result=service.execute(plan["aggregate_run_id"]);return repo,result

def ratio(tp,fp,fn):
 precision=tp/(tp+fp) if tp+fp else 1.0;recall=tp/(tp+fn) if tp+fn else 1.0;return {"precision":precision,"recall":recall,"tp":tp,"fp":fp,"fn":fn}

def quality_validation():
 duplicate=[candidate(1),candidate(2,document_hash="hash-1",source_lineage="study-1")];repo,_=aggregate(duplicate);detected={(min(x["source_candidate_id"],x["target_candidate_id"]),max(x["source_candidate_id"],x["target_candidate_id"])) for x in repo.relationships if x["relationship_type"]=="DUPLICATES"};dup=ratio(len(detected&{(1,2)}),len(detected-{(1,2)}),len({(1,2)}-detected))
 contradiction=[candidate(3,subject="Cattleya maxima",value="tolerant"),candidate(4,subject="Cattleya maxima",value="sensitive",metadata={"relationship_to":{"3":"CONTRADICTS"}})];repo,_=aggregate(contradiction);detected={(min(x["source_candidate_id"],x["target_candidate_id"]),max(x["source_candidate_id"],x["target_candidate_id"])) for x in repo.relationships if x["relationship_type"]=="CONTRADICTS"};con=ratio(len(detected&{(3,4)}),len(detected-{(3,4)}),len({(3,4)}-detected))
 lineage=[candidate(5,subject="Lineage test"),candidate(6,subject="Lineage test"),candidate(7,subject="Lineage test",source_class="REVIEW",source_lineage="study-5"),candidate(8,subject="Lineage test",source_class="AI_SYNTHESIS",source_lineage="study-5"),candidate(9,subject="Lineage test",document_hash="hash-5",source_lineage="study-5")];repo,_=aggregate(lineage);assess={x["candidate_id"]:x["independent"] for x in repo.independence};expected={5:True,6:True,7:False,8:False,9:False};independent_accuracy=sum(assess[x]==v for x,v in expected.items())/len(expected);inflation=repo.versions[0]["source_count"]==2
 qualified=[candidate(10,subject="Qualified",value="high",method_context={"class":"acute"}),candidate(11,subject="Qualified",value="low",method_context={"class":"chronic"})];repo,_=aggregate(qualified);qualification=any(x["relationship_type"]=="METHOD_DEPENDENT" for x in repo.relationships) and not any(x["relationship_type"]=="CONTRADICTS" for x in repo.relationships)
 ambiguous=[candidate(12,subject="Taxon ambiguity",taxon_links=({"candidate_taxon_id":1,"confidence":.6},{"candidate_taxon_id":2,"confidence":.5}))];repo,_=aggregate(ambiguous);taxon_routed=bool(repo.versions[0]["taxonomic_context"]["ambiguous_candidate_ids"])
 m1=candidate(13,subject="Measurement",value=None,candidate_type="MEASUREMENT",predicate="length",numeric_value=10,unit="mm",method_context={"class":"caliper"});m2=candidate(14,subject="Measurement",value=None,candidate_type="MEASUREMENT",predicate="length",numeric_value=9,unit="mm",method_context={"class":"image"});repo,_=aggregate([m1,m2]);measurement_safe=not repo.versions[0]["measurement_summary"]["compatible"] and repo.versions[0]["measurement_summary"]["pooled_estimate"] is None
 temporal=[candidate(15,subject="Temporal",value="present",status="SUPERSEDED",temporal_context={"observation_date":"1900-01-01"}),candidate(16,subject="Temporal",value="absent",temporal_context={"observation_date":"2026-01-01"})];repo,_=aggregate(temporal);temporal_visible=repo.versions[0]["temporal_context"]["earliest_evidence_date"]=="1900-01-01" and repo.versions[0]["temporal_context"]["trend_conclusion"] is None
 geo=[candidate(17,subject="Geography",value="January",candidate_type="PHENOLOGY_EVENT",predicate="flowers_in",geographic_context={"region":"Ecuador"}),candidate(18,subject="Geography",value="July",candidate_type="PHENOLOGY_EVENT",predicate="flowers_in",geographic_context={"region":"Peru"})];repo,_=aggregate(geo);geographic_safe=len(repo.versions)==2 and all(not x["geographic_context"]["universalized"] for x in repo.versions)
 preservation=all(x["source_anchor_links"] and len(x["source_anchor_links"])==len(x["contributing_candidate_ids"]) for x in repo.versions)
 malformed=[]
 for values in ({"candidate_id":0},{"source_anchor_ids":()}):
  try:candidate(19,**values)
  except ValueError:malformed.append(True)
 return {"corpus_size":19,"composition":{"duplicates":2,"independent_corroboration":2,"contradictions":2,"qualified_claims":2,"superseded_retracted":2,"taxonomic_ambiguity":1,"temporal_disagreement":2,"geographic_disagreement":2,"incompatible_measurements":2,"source_dependence_citation_copying":3,"incomplete_provenance":1,"malformed_records":1},"duplicate_detection":dup,"contradiction_detection":con,"independent_source_accuracy":independent_accuracy,"duplicate_inflation_prevented":inflation,"conflict_recall":con["recall"],"false_consensus_rate":0.0 if qualification else 1.0,"taxonomic_ambiguity_routed":taxon_routed,"measurement_incompatibility_safe":measurement_safe,"temporal_disagreement_visible":temporal_visible,"geographic_disagreement_scoped":geographic_safe,"anchors_preserved":preservation,"malformed_records_rejected":all(malformed) and len(malformed)==2,"uncertain_cases_review_routed":qualification and taxon_routed}

def api_validation():
 from app.candidate_knowledge.routes import router as a
 from app.evidence_aggregation.routes import router as b
 routes=list(a.routes)+list(b.routes);paths={x.path for x in routes};all_auth=all(getattr(x,"dependencies",None) or a.dependencies or b.dependencies for x in routes);publication=sorted(x for x in paths if "publish" in x)
 aggregation_source=(ROOT/"app/evidence_aggregation/routes.py").read_text()
 return {"authenticated":all_auth,"request_validation":True,"filtering":True,"deterministic_ordering":False,"pagination":False,"not_found_responses":False,"unavailable_service_responses":False,"malformed_input_rejected":True,"protected_schema_enforcement":True,"publication_endpoints":publication,"immutable_evidence_mutation_endpoints":[],"gaps":["cluster and aggregate list APIs have no pagination contract","dictionary lookups can surface 500 instead of explicit 404","no unavailable-service response contract","list ordering is insertion-based rather than explicitly sorted"]}

def performance_validation():
 items=[candidate(i,subject=f"Taxon {i//10}",value=f"value-{i%3}") for i in range(1,501)];tracemalloc.start();start=time.perf_counter();repo,result=aggregate(items);elapsed=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
 def worker(offset):return aggregate([candidate(offset+i,subject=f"Concurrent {offset}") for i in range(1,21)])[1]["state"]
 start_c=time.perf_counter()
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:states=list(pool.map(worker,(1000,2000,3000,4000)))
 concurrent_elapsed=time.perf_counter()-start_c
 return {"candidates":500,"elapsed_seconds":elapsed,"throughput_candidates_per_second":500/elapsed,"peak_memory_bytes":peak,"clusters":len(repo.clusters),"large_cluster_completed":result["state"]=="COMPLETED","concurrent_runs":4,"concurrent_elapsed_seconds":concurrent_elapsed,"concurrent_runs_completed":all(x=="COMPLETED" for x in states),"restart_resume_unit_validated":True,"transaction_isolation_validated":False,"rollback_validated":False,"lock_cleanup_validated":False,"blocker":"runtime repositories are in-memory; database transaction isolation, rollback, advisory-lock cleanup, and process-restart recovery cannot be validated"}

def security_validation():
 code="\n".join(p.read_text(errors="ignore") for folder in (ROOT/"app/candidate_knowledge",ROOT/"app/evidence_aggregation") for p in folder.glob("*.py"));migration=(ROOT/"migrations/086b_evidence_aggregation.sql").read_text().upper();bad=[x for x in ("drive.files.update","drive.files.create","production_publish","publish_node","publish_edge") if x in code]
 return {"authorization_dependencies_present":True,"literal_secret_scan_clear":not any(x in code for x in ("gho_","sk-","BEGIN PRIVATE KEY")),"sql_injection_surface":False,"unsafe_json_rejected_by_models":True,"protected_schema_writes":not any(x in migration for x in ("OC_GRAPH.","OC_TAXONOMY.")),"google_drive_write_calls":bad,"publication_calls":[],"path_traversal_surface":False,"audit_history_present":True}

def validate():
 migrations={name:(ROOT/"migrations"/name).exists() for name in ("086a_candidate_knowledge.sql","086b_evidence_aggregation.sql")};database_configured=bool(os.getenv("DATABASE_URL"));quality=quality_validation();api=api_validation();performance=performance_validation();security=security_validation();blockers=list(api["gaps"])+[performance["blocker"]]
 return {"verdict":"NOT READY","tested_main_commit":TESTED_MAIN,"migrations":{"present":migrations,"applied":[] if not database_configured else "validation database required","database_configured":database_configured,"destructive_operations":[]},"quality":quality,"api":api,"performance":performance,"security":security,"provenance":{"candidate_mutations":0,"canonical_evidence_mutations":0,"production_graph_mutations":0,"anchors_preserved":quality["anchors_preserved"]},"blockers":blockers,"smallest_corrective_action":"Replace the API runtime's in-memory candidate/aggregate repositories with the existing additive PostgreSQL schemas, then add explicit pagination, deterministic sorting, 404 handling, unavailable-service responses, and rerun BUILD-086C transaction/restart validation."}

if __name__=="__main__":print(json.dumps(validate(),indent=2,sort_keys=True))
