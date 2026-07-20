from __future__ import annotations
import hashlib,json,time
from dataclasses import asdict
from .models import Eligibility,IndexDocument,PlanAction
def digest(value): return hashlib.sha256((value if isinstance(value,str) else json.dumps(value,sort_keys=True,default=str,separators=(",",":"))).encode()).hexdigest()
def eligibility(doc,provider):
 if not doc.text.strip(): return Eligibility.EXCLUDED_EMPTY
 if not doc.internal_indexing_permission: return Eligibility.EXCLUDED_BY_POLICY
 if doc.display_policy=="UNKNOWN_REQUIRES_REVIEW" or doc.review_state=="REQUIRED": return Eligibility.EXCLUDED_REVIEW_REQUIRED
 if doc.temporal_status in {"SUPERSEDED","RETRACTED"}: return Eligibility.EXCLUDED_SUPERSEDED
 if doc.language not in {"en","la","es","fr","de"}: return Eligibility.EXCLUDED_UNSUPPORTED_LANGUAGE
 if not provider.metadata["local_execution"] and provider.metadata["data_handling"] not in {"RESTRICTED_ALLOWED","PUBLIC"}: return Eligibility.EXCLUDED_BY_POLICY
 return Eligibility.ELIGIBLE
class SemanticIndexService:
 def __init__(self,repository,provider,pipeline_version="085a-1",policy_version="1"): self.repo=repository; self.provider=provider; self.pipeline_version=pipeline_version; self.policy_version=policy_version
 def preview(self,documents,collections=None,configuration=None):
  cfg=configuration or {}; model=self.repo.ensure_model(self.provider.metadata); run=self.repo.create_run(model,digest(cfg),self.pipeline_version,self.policy_version,"PLANNING"); counts={}
  for doc in documents:
   decision=eligibility(doc,self.provider); content=digest(doc.text); metadata=digest({k:v for k,v in asdict(doc).items() if k!="text"}); previous=self.repo.latest(doc.source_object_type,doc.source_object_id)
   if decision!=Eligibility.ELIGIBLE: action=PlanAction.REVIEW_REQUIRED if decision==Eligibility.EXCLUDED_REVIEW_REQUIRED else (PlanAction.TOMBSTONE_REQUIRED if previous else PlanAction.POLICY_EXCLUDED)
   elif not previous: action=PlanAction.NEW
   elif previous["model_id"]!=model: action=PlanAction.MODEL_CHANGED
   elif previous["configuration_hash"]!=digest(cfg): action=PlanAction.CONFIGURATION_CHANGED
   elif previous["content_hash"]!=content: action=PlanAction.CHANGED_TEXT
   elif previous["metadata_hash"]!=metadata: action=PlanAction.CHANGED_METADATA
   else: action=PlanAction.UNCHANGED
   self.repo.plan_item(run,doc,decision.value,action.value,content,metadata); counts[action.value]=counts.get(action.value,0)+1
  self.repo.transition(run,"PLANNED"); return {"index_run_id":run,"state":"PLANNED","counts":counts,"vectors_created":0}
 def execute(self,run_id,batch_size=32):
  self.repo.transition(run_id,"INDEXING"); started=time.perf_counter()
  for item in self.repo.pending_items(run_id):
   if self.repo.cancel_requested(run_id): self.repo.transition(run_id,"CANCELLED"); return self.repo.status(run_id)
   try:
    if item["action"]==PlanAction.UNCHANGED: self.repo.reuse(item); continue
    if item["action"]==PlanAction.TOMBSTONE_REQUIRED: self.repo.tombstone(item,"POLICY_OR_SOURCE_STATE_CHANGED"); continue
    if item["eligibility"]!=Eligibility.ELIGIBLE: self.repo.exclude(item); continue
    vector=self.provider.embed_batch([item["document"].text])[0]
    if len(vector)!=self.provider.metadata["dimension"]: raise ValueError("VECTOR_DIMENSION_MISMATCH")
    self.repo.persist(item,vector,self.provider.count_tokens(item["document"].text))
   except Exception as exc: self.repo.fail(item,type(exc).__name__,str(exc))
  self.repo.finish(run_id,time.perf_counter()-started); return self.repo.status(run_id)
 def cancel(self,run_id): return self.repo.request_cancel(run_id)
 def resume(self,run_id): self.repo.clear_cancel(run_id); return self.execute(run_id)
