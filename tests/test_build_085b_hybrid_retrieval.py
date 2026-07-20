import pytest
from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.evaluation import evaluate
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.provider import DeterministicLocalProvider

def corpus():
 r=MemoryIndexRepository(); p=DeterministicLocalProvider(); model=r.ensure_model(p.metadata)
 rows=[(1,"PROTOCOL","Complete asymbiotic germination protocol",1,"FULL_TEXT_ALLOWED",{"peer_reviewed":"YES","evidence_type":"PRIMARY"}),(2,"PROTOCOL","germination protocol incidental",2,"METADATA_ONLY",{}),(3,"IDENTIFICATION_KEY","Identification keys for Phragmipedium",3,"FULL_TEXT_ALLOWED",{}),(4,"STRATEGIC_INSIGHT","educational reports teaching modalities",4,"LIMITED_PREVIEW_ONLY",{"excerpt_limit":12}),(5,"CANDIDATE_EVENT","current grant opportunities orchid conservation",5,"FULL_TEXT_ALLOWED",{"temporal_status":"TIME_SENSITIVE","current":True}),(6,"CANDIDATE_EVENT","expired grant orchid conservation",6,"FULL_TEXT_ALLOWED",{"expires_at":"2020","as_of":"2026"}),(7,"INTERNAL_REPORT","BUILD decisions semantic indexing",7,"INTERNAL_RESEARCH_ONLY",{"internal_access_allowed":True})]
 parents={}
 for i,typ,text,rev,policy,extra in rows:
  d={"index_document_id":i,"source_object_type":typ,"source_object_id":i,"revision_id":rev,"parent_type":typ,"parent_id":i,"anchors":(i*10,),"content_hash":str(i),"metadata_hash":str(i),"model_id":model,"configuration_hash":"c","active":True,"version":1,"metadata":{"display_policy":policy,"document_title":text,"title":text,"document_class":"EDUCATIONAL_MATERIAL" if i==4 else "PRIMARY_RESEARCH","collections":["GENERAL_BRAIN"],"verification_state":"VERIFIED","locator":{"page":i},**extra}}; r.documents.append(d); r.lexical.append({"index_document_id":i,"normalized_text":text.casefold(),"language":"en","title":text}); r.vectors.append({"index_document_id":i,"vector":p.embed_batch([text])[0],"active":True}); parents[(typ,i)]={"complete_text":text*30,"internal_access_allowed":extra.get("internal_access_allowed",False),"components":["table","figure","caption"]};
 return r,p,parents
def test_query_validation_limits_modes_and_pagination():
 assert RetrievalQuery(" a   query ").text=="a query"
 for kw in ({"limit":101},{"mode":"BAD"},{"parent_expansion":"BAD"},{"text":"x"*501}):
  with pytest.raises(ValueError): RetrievalQuery(**({"text":"x"}|kw))
def test_lexical_title_object_collection_active_and_tombstone_filters():
 r,p,parents=corpus(); e=RetrievalEngine(r,p,parents); result=e.search(RetrievalQuery("asymbiotic germination",mode="LEXICAL",object_types=("PROTOCOL",),collections=("GENERAL_BRAIN",)))
 assert result["results"][0]["citation"]["canonical_object_id"]==1 and result["results"][0]["score_breakdown"]["lexical"]>0
def test_semantic_model_dimension_and_hybrid_explanation_deterministic():
 r,p,parents=corpus(); e=RetrievalEngine(r,p,parents); q=RetrievalQuery("identification keys Phragmipedium"); a=e.search(q); b=e.search(q); assert [x["citation"]["canonical_object_id"] for x in a["results"]]==[x["citation"]["canonical_object_id"] for x in b["results"]] and a["results"][0]["ranking_explanation"]
def test_reliability_time_expiration_historical_and_ai_signal():
 r,p,parents=corpus(); e=RetrievalEngine(r,p,parents); current=e.search(RetrievalQuery("grant orchid conservation")); assert 6 not in [x["citation"]["canonical_object_id"] for x in current["results"]] and current["excluded_counts"]["EXPIRED"]==1
 historical=e.search(RetrievalQuery("grant orchid conservation",historical=True)); assert 6 in [x["citation"]["canonical_object_id"] for x in historical["results"]]
def test_dedup_source_diversity_and_distinct_parent_access():
 r,p,parents=corpus(); duplicate=dict(r.documents[0]); duplicate.update(index_document_id=20); r.documents.append(duplicate); r.lexical.append({"index_document_id":20,"normalized_text":"complete asymbiotic germination protocol","language":"en","title":"same"}); r.vectors.append({"index_document_id":20,"vector":p.embed_batch(["same"])[0],"active":True}); result=RetrievalEngine(r,p,parents).search(RetrievalQuery("germination protocol",per_source_limit=1)); assert result["deduplicated_count"]>=1
def test_parent_expansion_protocol_key_and_restricted_policy():
 r,p,parents=corpus(); e=RetrievalEngine(r,p,parents); protocol=e.search(RetrievalQuery("asymbiotic",parent_expansion="COMPLETE_PROTOCOL"))["results"][0]; assert protocol["complete_object"] and len(protocol["parent_expansion"]["object"]["complete_text"])>100
 restricted=e.search(RetrievalQuery("incidental",mode="LEXICAL",parent_expansion="COMPLETE_PROTOCOL"))["results"][0]; assert restricted["authorized_excerpt"] is None and restricted["parent_expansion"]["denied"]=="DISPLAY_POLICY"
def test_all_display_policies_and_no_locator_fabrication():
 r,p,parents=corpus(); e=RetrievalEngine(r,p,parents)
 result=e.search(RetrievalQuery("BUILD decisions semantic indexing",mode="LEXICAL"))["results"][0]; assert result["authorized_excerpt"] is None
 internal=e.search(RetrievalQuery("BUILD decisions semantic indexing",mode="LEXICAL",internal_access=True))["results"][0]; assert internal["authorized_excerpt"]
 r.documents[0]["metadata"].pop("locator"); no_locator=e.search(RetrievalQuery("asymbiotic",mode="LEXICAL"))["results"][0]; assert no_locator["citation"]["locator"]=="EXACT_LOCATOR_UNAVAILABLE"
def test_evaluation_metrics_and_required_behavior_cases():
 r,p,parents=corpus(); e=RetrievalEngine(r,p,parents); cases=[{"name":"protocol","query":RetrievalQuery("asymbiotic germination",object_types=("PROTOCOL",)),"expected_ids":[1]},{"name":"key","query":RetrievalQuery("identification keys Phragmipedium"),"expected_ids":[3]},{"name":"education","query":RetrievalQuery("teaching modalities"),"expected_ids":[4]},{"name":"build","query":RetrievalQuery("BUILD decisions semantic indexing",internal_access=True),"expected_ids":[7]}]; report=evaluate(cases,e.search); assert report["mean_mrr"]>.5 and all(x["citation_completeness"]>0 for x in report["cases"])
def test_api_is_read_only_and_safety_contract():
 from pathlib import Path
 from app.evidence_retrieval.routes import router
 assert all(getattr(x,"methods",set())<={"GET","POST"} for x in router.routes); code="\n".join(x.read_text() for x in Path("app/evidence_retrieval").glob("*.py")); assert all(x not in code for x in ("production_publish","drive.files.update","adapted_protocol","recommend_conservation","question_answer"))
