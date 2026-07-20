from pathlib import Path
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.models import IndexDocument
from app.semantic_index.provider import DeterministicLocalProvider,ProviderError
from app.semantic_index.service import SemanticIndexService,eligibility

def doc(i=1,**kw):
 values={"source_object_type":"PROTOCOL","source_object_id":i,"revision_id":1,"extraction_run_id":1,"text":"complete protocol evidence","parent_type":"PROTOCOL","parent_id":i,"source_anchor_ids":(11,12),"internal_indexing_permission":True,"display_policy":"INTERNAL_RESEARCH_ONLY","metadata":{"document_class":"PRIMARY_RESEARCH"}}; values.update(kw); return IndexDocument(**values)
def setup(provider=None): r=MemoryIndexRepository(); return r,SemanticIndexService(r,provider or DeterministicLocalProvider())
def test_migration_additive_and_links_build084():
 sql=Path("migrations/085_semantic_index.sql").read_text(); assert "CREATE SCHEMA IF NOT EXISTS oc_semantic_index" in sql and "oc_document_intelligence.extraction_runs" in sql and "oc_import.document_revisions" in sql
 assert all(x not in sql.upper() for x in ("DROP ","TRUNCATE ","OC_GRAPH.","OC_TAXONOMY."))
def test_deterministic_provider_batch_tokens_dimensions_and_no_network():
 p=DeterministicLocalProvider(6); assert p.embed_batch(["same","same"])[0]==p.embed_batch(["same"])[0] and len(p.embed_batch(["x"])[0])==6 and p.count_tokens("a b")==2 and p.metadata["local_execution"]
 try:p.embed_batch([""])
 except ProviderError as e: assert not e.retryable
def test_eligibility_conservative_and_auth_irrelevant():
 p=DeterministicLocalProvider(); assert eligibility(doc(),p)=="ELIGIBLE"; assert eligibility(doc(internal_indexing_permission=False),p)=="EXCLUDED_BY_POLICY"; assert eligibility(doc(display_policy="UNKNOWN_REQUIRES_REVIEW"),p)=="EXCLUDED_REVIEW_REQUIRED"
def test_preview_writes_no_vectors_and_parent_anchor_metadata_retained():
 r,s=setup(); plan=s.preview([doc()]); assert plan["counts"]=={"NEW":1} and not r.vectors; result=s.execute(plan["index_run_id"]); assert result["state"]=="COMPLETED" and r.documents[0]["parent_id"]==1 and r.documents[0]["anchors"]==(11,12)
def test_idempotency_changed_content_model_and_configuration_keep_history():
 r,s=setup(); a=s.preview([doc()]); s.execute(a["index_run_id"]); b=s.preview([doc()]); s.execute(b["index_run_id"]); assert b["counts"]=={"UNCHANGED":1} and len(r.vectors)==1
 c=s.preview([doc(text="changed")]); s.execute(c["index_run_id"]); assert len(r.vectors)==2 and len(r.documents)==2 and not r.documents[0]["active"]
 d=SemanticIndexService(r,DeterministicLocalProvider(12)).preview([doc(text="changed")]); assert d["counts"]=={"MODEL_CHANGED":1}
 e=s.preview([doc(text="changed")],configuration={"normalize":True}); assert e["counts"]=={"CONFIGURATION_CHANGED":1}
def test_failure_partial_resume_and_completed_items_survive():
 class Flaky(DeterministicLocalProvider):
  def embed_batch(self,texts):
   if "fail" in texts[0]: raise ProviderError("temporary",True)
   return super().embed_batch(texts)
 r,s=setup(Flaky()); p=s.preview([doc(1),doc(2,text="fail")]); result=s.execute(p["index_run_id"]); assert result["state"]=="PARTIAL" and len(r.vectors)==1 and r.warnings
 r.items[p["index_run_id"]][1]["document"]=doc(2,text="recovered"); assert s.resume(p["index_run_id"])["state"]=="COMPLETED" and len(r.vectors)==2
def test_cancel_preserves_progress_and_tombstone_preserves_canonical_identity():
 r,s=setup(); p=s.preview([doc()]); s.cancel(p["index_run_id"]); assert s.execute(p["index_run_id"])["state"]=="CANCELLED"
 s.resume(p["index_run_id"]); excluded=doc(1,internal_indexing_permission=False); q=s.preview([excluded]); assert q["counts"]=={"TOMBSTONE_REQUIRED":1}; s.execute(q["index_run_id"]); assert r.tombstones[0]["prior_index_document_id"] and r.documents[0]["revision_id"]==1
def test_lexical_record_and_safety_contract():
 r,s=setup(); p=s.preview([doc()]); s.execute(p["index_run_id"]); assert r.lexical[0]["normalized_text"]=="complete protocol evidence"
 code="\n".join(x.read_text() for x in Path("app/semantic_index").glob("*.py")); assert all(x not in code for x in ("drive.files.update","production_publish","question_answer","knowledge_extract"))
