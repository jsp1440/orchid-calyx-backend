import concurrent.futures,time
from pathlib import Path
from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.evaluation import evaluate
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.models import IndexDocument
from app.semantic_index.provider import DeterministicLocalProvider
from app.semantic_index.service import SemanticIndexService

def foundation():
 r=MemoryIndexRepository(); p=DeterministicLocalProvider(); s=SemanticIndexService(r,p); parents={}; docs=[]
 rows=[(1,"PROTOCOL","Complete asymbiotic germination protocols reagents timing controls",1,"FULL_TEXT_ALLOWED","PRIMARY_RESEARCH"),(2,"SECTION","incidental mention of germination",2,"FULL_TEXT_ALLOWED","REVIEW_SYNTHESIS"),(3,"PROTOCOL","Dracula pollination study direct observation",3,"FULL_TEXT_ALLOWED","PRIMARY_RESEARCH"),(4,"CLAIM","Cattleya maxima heat tolerance measurement conflicting evidence",4,"FULL_TEXT_ALLOWED","PRIMARY_RESEARCH"),(5,"STRATEGIC_INSIGHT","educational reports teaching modalities learning objectives",5,"LIMITED_PREVIEW_ONLY","EDUCATIONAL_MATERIAL"),(6,"STRATEGIC_INSIGHT","conservation assessment cloud forests threats gaps recommendations",6,"FULL_TEXT_ALLOWED","CONSERVATION_ASSESSMENT"),(7,"CANDIDATE_EVENT","current grant opportunities orchid conservation partnership",7,"FULL_TEXT_ALLOWED","INTELLIGENCE_REPORT"),(8,"CANDIDATE_EVENT","expired grant orchid conservation",8,"FULL_TEXT_ALLOWED","INTELLIGENCE_REPORT"),(9,"IDENTIFICATION_KEY","identification keys Phragmipedium couplet branch",9,"FULL_TEXT_ALLOWED","TAXONOMIC_WORK"),(10,"INTERNAL_REPORT","BUILD decisions semantic indexing rationale dependency risk",10,"INTERNAL_RESEARCH_ONLY","INTERNAL_ORGANIZATIONAL"),(11,"SECTION","secret restricted query phrase",11,"METADATA_ONLY","TECHNICAL_REPORT"),(12,"SECTION","Complete asymbiotic germination protocols reagents timing controls",12,"FULL_TEXT_ALLOWED","PRIMARY_RESEARCH")]
 for oid,typ,text,rev,policy,cls in rows:
  temporal="TIME_SENSITIVE" if typ=="CANDIDATE_EVENT" else "CURRENT_REFERENCE"; meta={"document_title":text,"authors":["Fixture Author"],"publication_date":"2026-01-01","source_type":"FIXTURE","locator":{"page":oid},"peer_reviewed":"YES" if cls=="PRIMARY_RESEARCH" else "NO","evidence_type":"PRIMARY" if cls=="PRIMARY_RESEARCH" else "SYNTHESIS","citations_verified":"YES","excerpt_limit":10,"internal_access_allowed":typ=="INTERNAL_REPORT","expires_at":"2020" if oid==8 else None,"as_of":"2026","current":oid==7}
  d=IndexDocument(typ,oid,rev,1,text,parent_type=typ,parent_id=oid,collections=("GENERAL_BRAIN",),title=text,source_anchor_ids=(oid*10,),document_class=cls,temporal_status=temporal,verification_state="VERIFIED",internal_indexing_permission=True,display_policy=policy,metadata=meta); docs.append(d); parents[(typ,oid)]={"complete_text":text*100,"ordered_anchors":[oid*10],"internal_access_allowed":oid==10,"components":["methods","table","figure","caption","limitations"]}
 plan=s.preview(docs); assert plan["vectors_created"]==0; s.execute(plan["index_run_id"]); return r,p,s,parents,docs

def test_end_to_end_evidence_to_active_index_to_retrieval():
 r,p,s,parents,docs=foundation(); assert len(r.documents)==len(docs)==len(r.vectors)==len(r.lexical); assert all(x["dimension"]==p.metadata["dimension"] for x in r.vectors); assert all(x["anchors"] and x["parent_id"] and x["revision_id"] for x in r.documents)
 result=RetrievalEngine(r,p,parents).search(RetrievalQuery("asymbiotic germination protocols",object_types=("PROTOCOL",),parent_expansion="COMPLETE_PROTOCOL")); assert result["results"][0]["complete_object"] and result["results"][0]["citation"]["source_anchor_ids"]

def test_quality_thresholds_determinism_citations_parent_copyright_and_duplicates():
 r,p,s,parents,docs=foundation(); e=RetrievalEngine(r,p,parents); cases=[("protocol","asymbiotic germination protocols",1),("pollination","pollination Dracula",3),("heat","heat tolerance Cattleya maxima",4),("education","teaching modalities",5),("conservation","cloud forests conservation",6),("grant","current grant opportunities",7),("key","identification keys Phragmipedium",9),("build","BUILD decisions semantic indexing",10)]
 report=evaluate([{"name":n,"query":RetrievalQuery(q,internal_access=True),"expected_ids":[i]} for n,q,i in cases],e.search); assert report["mean_mrr"]>=.9; assert all(x["citation_completeness"]==1 and x["parent_correctness"]==1 and x["copyright_correctness"]==1 for x in report["cases"])
 q=RetrievalQuery("asymbiotic germination protocols",limit=5); a=e.search(q); b=e.search(q); assert [x["result_id"] for x in a["results"]]==[x["result_id"] for x in b["results"]] and a["deduplicated_count"]>=1

def test_all_policies_and_no_restricted_leaks_in_scores_terms_or_errors():
 r,p,s,parents,docs=foundation(); e=RetrievalEngine(r,p,parents); secret=e.search(RetrievalQuery("secret restricted query phrase",mode="LEXICAL"))["results"][0]; assert secret["authorized_excerpt"] is None and not secret["matched_terms"] and "secret" not in str(secret["ranking_explanation"])
 internal=e.search(RetrievalQuery("BUILD decisions semantic indexing",mode="LEXICAL"))["results"][0]; assert internal["authorized_excerpt"] is None; assert e.search(RetrievalQuery("BUILD decisions semantic indexing",mode="LEXICAL",internal_access=True))["results"][0]["authorized_excerpt"]

def test_idempotency_refresh_model_version_tombstone_and_historical_audit():
 r,p,s,parents,docs=foundation(); first=len(r.vectors); same=s.preview(docs); assert same["counts"]=={"UNCHANGED":len(docs)}; s.execute(same["index_run_id"]); assert len(r.vectors)==first
 changed=list(docs); changed[0]=IndexDocument(**{**docs[0].__dict__,"text":docs[0].text+" changed"}); plan=s.preview(changed); s.execute(plan["index_run_id"]); versions=[x for x in r.documents if x["source_object_id"]==1]; assert len(versions)==2 and sum(x["active"] for x in versions)==1
 excluded=IndexDocument(**{**changed[0].__dict__,"internal_indexing_permission":False}); tomb=s.preview([excluded]); s.execute(tomb["index_run_id"]); assert r.tombstones and not any(x["active"] for x in r.documents if x["source_object_id"]==1)

def test_failure_resume_cancellation_and_bounded_performance_concurrency():
 r,p,s,parents,docs=foundation(); e=RetrievalEngine(r,p,parents); start=time.perf_counter();
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(lambda _:e.search(RetrievalQuery("orchid conservation",limit=5)),range(30)))
 elapsed=time.perf_counter()-start; assert elapsed<5 and all(x["elapsed_ms"]<1000 for x in results)
 plan=s.preview([IndexDocument(**{**docs[0].__dict__,"source_object_id":99})]); s.cancel(plan["index_run_id"]); assert s.execute(plan["index_run_id"])["state"]=="CANCELLED"; assert s.resume(plan["index_run_id"])["state"]=="COMPLETED"

def test_api_safety_schema_and_no_mutation_surface():
 from app.evidence_retrieval.routes import router
 mutations=[x for x in router.routes if getattr(x,"methods",set())&{"PUT","PATCH","DELETE"}]; assert not mutations
 code="\n".join(x.read_text() for x in Path("app/evidence_retrieval").glob("*.py")); assert all(x not in code for x in ("drive.files.update","production_publish","knowledge_graph","final_answer","adapted_protocol"))
 sql=Path("migrations/085_semantic_index.sql").read_text().upper(); assert "DROP " not in sql and "TRUNCATE " not in sql and "OC_GRAPH." not in sql and "OC_TAXONOMY." not in sql
