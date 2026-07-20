from copy import deepcopy
class MemoryIndexRepository:
 def __init__(self): self.models={}; self.runs={}; self.items={}; self.documents=[]; self.vectors=[]; self.lexical=[]; self.tombstones=[]; self.warnings=[]; self.reviews=[]; self._id=1; self.cancelled=set()
 def _next(self): x=self._id; self._id+=1; return x
 def ensure_model(self,m): key=(m["provider_name"],m["model_name"],m["model_version"],m["dimension"]); self.models.setdefault(key,self._next()); return self.models[key]
 def create_run(self,model,config,pipeline,policy,state): rid=self._next(); self.runs[rid]={"index_run_id":rid,"model_id":model,"configuration_hash":config,"pipeline_version":pipeline,"policy_version":policy,"state":state,"metrics":{"planned":0,"indexed":0,"reused":0,"excluded":0,"failed":0,"tokens":0,"provider_calls":0}}; self.items[rid]=[]; return rid
 def transition(self,rid,state): self.runs[rid]["state"]=state
 def plan_item(self,rid,doc,eligible,action,content,metadata): self.items[rid].append({"item_id":self._next(),"run_id":rid,"document":doc,"eligibility":eligible,"action":action,"content_hash":content,"metadata_hash":metadata,"state":"PLANNED"}); self.runs[rid]["metrics"]["planned"]+=1
 def latest(self,t,i): return next((d for d in reversed(self.documents) if d["source_object_type"]==t and d["source_object_id"]==i and d["active"]),None)
 def pending_items(self,rid): return [x for x in self.items[rid] if x["state"] in {"PLANNED","FAILED"}]
 def persist(self,item,vector,tokens):
  was_failed=item["state"]=="FAILED"
  old=self.latest(item["document"].source_object_type,item["document"].source_object_id)
  if old: old["active"]=False
  doc=item["document"]; metadata={**doc.metadata,"collections":list(doc.collections),"document_class":doc.document_class,"intended_consumers":list(doc.intended_consumers),"temporal_status":doc.temporal_status,"verification_state":doc.verification_state,"review_state":doc.review_state,"display_policy":doc.display_policy,"representation_type":doc.representation_type,"internal_indexing_permission":doc.internal_indexing_permission}
  run=self.runs[item["run_id"]]; ident=self._next(); d={"index_document_id":ident,"source_object_type":doc.source_object_type,"source_object_id":doc.source_object_id,"revision_id":doc.revision_id,"extraction_run_id":doc.extraction_run_id,"parent_type":doc.parent_type,"parent_id":doc.parent_id,"anchors":doc.source_anchor_ids,"content_hash":item["content_hash"],"metadata_hash":item["metadata_hash"],"model_id":run["model_id"],"configuration_hash":run["configuration_hash"],"active":True,"version":1+(old["version"] if old else 0),"metadata":metadata}; self.documents.append(d); self.vectors.append({"index_document_id":ident,"vector":vector,"dimension":len(vector),"active":True,"run_id":item["run_id"]}); self.lexical.append({"index_document_id":ident,"normalized_text":doc.text.casefold(),"language":doc.language,"title":doc.title}); item["state"]="INDEXED"; run["metrics"].update(indexed=run["metrics"]["indexed"]+1,tokens=run["metrics"]["tokens"]+tokens,provider_calls=run["metrics"]["provider_calls"]+1,failed=max(0,run["metrics"]["failed"]-(1 if was_failed else 0)))
 def reuse(self,item): item["state"]="REUSED"; self.runs[item["run_id"]]["metrics"]["reused"]+=1
 def exclude(self,item): item["state"]="EXCLUDED"; self.runs[item["run_id"]]["metrics"]["excluded"]+=1; self.reviews.append({"item_id":item["item_id"],"state":"OPEN","reason":item["eligibility"]}) if item["action"]=="REVIEW_REQUIRED" else None
 def tombstone(self,item,reason): old=self.latest(item["document"].source_object_type,item["document"].source_object_id); old and old.update(active=False); self.tombstones.append({"source_object_type":item["document"].source_object_type,"source_object_id":item["document"].source_object_id,"prior_index_document_id":old and old["index_document_id"],"reason":reason,"replacement_id":None,"actor":"index-policy"}); item["state"]="TOMBSTONED"
 def fail(self,item,code,message): item["state"]="FAILED"; self.warnings.append({"item_id":item["item_id"],"code":code,"message":message}); self.runs[item["run_id"]]["metrics"]["failed"]+=1
 def finish(self,rid,elapsed): r=self.runs[rid]; r["metrics"]["elapsed_seconds"]=elapsed; r["state"]="PARTIAL" if r["metrics"]["failed"] else "COMPLETED"
 def request_cancel(self,rid): self.cancelled.add(rid); self.runs[rid]["state"]="CANCELLING"; return self.status(rid)
 def clear_cancel(self,rid): self.cancelled.discard(rid)
 def cancel_requested(self,rid): return rid in self.cancelled
 def status(self,rid): return deepcopy(self.runs[rid])
