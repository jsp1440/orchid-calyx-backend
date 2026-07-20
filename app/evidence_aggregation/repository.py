from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from typing import Any
def now(): return datetime.now(timezone.utc).isoformat()

class MemoryAggregateRepository:
 def __init__(self):
  self.runs={}; self.items={}; self.clusters={}; self.members=[]; self.aggregates=[]; self.versions=[]; self.evidence=[]; self.relationships=[]; self.independence=[]; self.conflicts={}; self.reviews={}; self.warnings=[]; self.events=[]; self.tombstones=[]; self.rulesets={"086b-rules-1":{"deterministic":True}}; self.models={"086b-local-1":{"network":False}}; self.cancelled=set(); self._id=1
 def next(self): value=self._id; self._id+=1; return value
 def create_run(self,config,ruleset,model,policies):
  rid=self.next(); self.runs[rid]={"aggregate_run_id":rid,"state":"PLANNING","configuration_hash":config,"ruleset_version":ruleset,"model_version":model,"policies":deepcopy(policies),"last_completed_item_id":None,"metrics":{"planned_candidates":0,"processed_candidates":0,"clusters_created":0,"clusters_reused":0,"aggregates_created":0,"aggregates_reused":0,"aggregate_versions_created":0,"support_links":0,"contradiction_links":0,"duplicate_links":0,"source_dependence_links":0,"review_items":0,"conflict_groups":0,"tombstones":0,"failed_clusters":0,"retries":0},"created_at":now()}; self.items[rid]=[]; return rid
 def transition(self,rid,state): self.runs[rid]["state"]=state; self.runs[rid]["updated_at"]=now(); return self.status(rid)
 def status(self,rid): return deepcopy(self.runs[rid])
 def review(self,rid,category,evidence,candidate_ids=(),cluster_id=None,severity="MEDIUM"):
  ident=self.next(); value={"review_id":ident,"aggregate_run_id":rid,"cluster_id":cluster_id,"candidate_ids":list(candidate_ids),"category":category,"severity":severity,"evidence":deepcopy(evidence),"state":"OPEN","created_at":now()}; self.reviews[ident]=value
  if rid in self.runs: self.runs[rid]["metrics"]["review_items"]+=1
  return value
 def resolve_review(self,ident,action,rationale,actor):
  allowed={"APPROVE_CLUSTER","SPLIT_CLUSTER","MERGE_CLUSTERS","VERIFY_SUPPORT","VERIFY_CONTRADICTION","MARK_SOURCE_DEPENDENCE","MARK_SOURCE_INDEPENDENCE","RESOLVE_TAXON_AMBIGUITY","ACCEPT_MEASUREMENT_COMPATIBILITY","REJECT_MEASUREMENT_COMPATIBILITY","ASSIGN_CONSENSUS_STATUS","PRESERVE_UNRESOLVED_CONFLICT","SUPERSEDE_AGGREGATE","WITHDRAW_AGGREGATE","DEFER"}
  if action not in allowed: raise ValueError("INVALID_REVIEW_ACTION")
  if not rationale.strip(): raise ValueError("RATIONALE_REQUIRED")
  value=self.reviews[ident]; value.update(state="RESOLVED",action=action,rationale=rationale,actor=actor,resolved_at=now()); self.events.append({"event_id":self.next(),"event_type":"REVIEW_RESOLVED","review_id":ident,"actor":actor,"created_at":now()}); return deepcopy(value)
 def request_cancel(self,rid): self.cancelled.add(rid); return self.transition(rid,"CANCELLING")
 def clear_cancel(self,rid): self.cancelled.discard(rid)
