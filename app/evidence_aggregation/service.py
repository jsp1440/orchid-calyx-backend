from __future__ import annotations
import hashlib,json,math,time
from collections import Counter,defaultdict
from dataclasses import asdict
from typing import Any
from .models import AggregateType,CANDIDATE_TYPE_MAP,CandidateInput,ConsensusStatus,EvidenceRelationship
from .repository import MemoryAggregateRepository,now
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,default=str,separators=(",",":")).encode()).hexdigest()
def norm(v): return " ".join(str(v).casefold().split())
UNIT_FACTORS={"mm":("length",1.0),"cm":("length",10.0),"m":("length",1000.0),"c":("temperature",1.0),"°c":("temperature",1.0)}

class EvidenceAggregationService:
 def __init__(self,repo,ruleset="086b-rules-1",model="086b-local-1",normalization="086b-norm-1"): self.repo=repo; self.ruleset=ruleset; self.model=model; self.normalization=normalization
 def preview(self,candidates,filters=None,policies=None):
  if not candidates: raise ValueError("CANDIDATES_REQUIRED")
  policy={"source_independence":"086b-source-1","taxon":"086b-taxon-1","measurement":"086b-measure-1","temporal":"086b-time-1","geographic":"086b-geo-1","copyright":"086b-copyright-1",**(policies or {})}; rid=self.repo.create_run(digest({"filters":filters or {},"policy":policy}),self.ruleset,self.model,policy); grouped=self._group(candidates); counts=Counter(); source_counts=Counter(x.source_class for x in candidates); review_counts=Counter(x.review_state for x in candidates); confidence=Counter("HIGH" if x.confidence>=.8 else "MEDIUM" if x.confidence>=.5 else "LOW" for x in candidates)
  for key,members in grouped.items():
   identity=self._identity(key,members,policy); existing=next((v for v in reversed(self.repo.versions) if v["identity_hash"]==identity),None); action="EXISTING_CLUSTER_UNCHANGED" if existing else "NEW_CLUSTER"; item_id=self.repo.next(); self.repo.items[rid].append({"item_id":item_id,"cluster_key":key,"candidates":members,"candidate_version_ids":[f"{x.candidate_id}:{x.candidate_version}" for x in members],"plan_action":action,"state":"PLANNED","failure":None}); counts[action]+=1
  self.repo.runs[rid]["metrics"]["planned_candidates"]=len(candidates); self.repo.transition(rid,"PLANNED"); return {"aggregate_run_id":rid,"state":"PLANNED","candidate_population":len(candidates),"candidate_versions":[f"{x.candidate_id}:{x.candidate_version}" for x in candidates],"filters":filters or {},"candidate_types":dict(Counter(x.candidate_type for x in candidates)),"source_classes":dict(source_counts),"review_states":dict(review_counts),"confidence_bands":dict(confidence),"ruleset_version":self.ruleset,"model_version":self.model,"policies":policy,"plan_counts":dict(counts),"aggregates_created":0}
 def _group(self,candidates):
  groups=defaultdict(list)
  for c in candidates:
   at=CANDIDATE_TYPE_MAP.get(c.candidate_type,AggregateType.TRAIT_AGGREGATE); geo=c.geographic_context.get("region") or c.geographic_context.get("country") if c.candidate_type in {"PHENOLOGY_EVENT","GEOGRAPHIC_OCCURRENCE"} else None; taxon=tuple(sorted(str(x.get("candidate_taxon_id") or x.get("source_name")) for x in c.taxon_links)); groups[(at.value,norm(c.normalized_subject),norm(c.predicate),geo,None,taxon)].append(c)
  return groups
 def _identity(self,key,members,policy): return digest({"key":key,"members":sorted(f"{x.candidate_id}:{x.candidate_version}" for x in members),"ruleset":self.ruleset,"model":self.model,"normalization":self.normalization,"policies":policy})
 def execute(self,rid):
  started=time.perf_counter(); self.repo.transition(rid,"AGGREGATING")
  for item in self.repo.items[rid]:
   if item["state"] not in {"PLANNED","FAILED"}: continue
   if rid in self.repo.cancelled: return self.repo.transition(rid,"CANCELLED")
   try: self._process(rid,item); self.repo.runs[rid]["last_completed_item_id"]=item["item_id"]
   except Exception as exc: item.update(state="FAILED",failure={"code":type(exc).__name__,"message":type(exc).__name__}); self.repo.warnings.append({"item_id":item["item_id"],"code":type(exc).__name__}); self.repo.runs[rid]["metrics"]["failed_clusters"]+=1; self.repo.review(rid,"FAILED_VALIDATION",item["failure"],severity="HIGH")
  self.repo.runs[rid]["metrics"]["elapsed_seconds"]=time.perf_counter()-started; state="PARTIAL" if any(x["state"]=="FAILED" for x in self.repo.items[rid]) else "COMPLETED"; return self.repo.transition(rid,state)
 def _process(self,rid,item):
  members=item["candidates"]; key=item["cluster_key"]; policy=self.repo.runs[rid]["policies"]; identity=self._identity(key,members,policy); existing=next((v for v in reversed(self.repo.versions) if v["identity_hash"]==identity),None)
  if existing: item["state"]="REUSED"; self.repo.runs[rid]["metrics"]["clusters_reused"]+=1; self.repo.runs[rid]["metrics"]["aggregates_reused"]+=1; return
  cluster=next((c for c in self.repo.clusters.values() if c["cluster_key"]==key and c["active"]),None)
  if not cluster: cid=self.repo.next(); cluster={"cluster_id":cid,"cluster_key":key,"aggregate_type":key[0],"active":True,"review_state":"REQUIRED","created_at":now()}; self.repo.clusters[cid]=cluster; self.repo.runs[rid]["metrics"]["clusters_created"]+=1
  cid=cluster["cluster_id"]
  for c in members:
   if not any(x["cluster_id"]==cid and x["candidate_id"]==c.candidate_id and x["candidate_version"]==c.candidate_version for x in self.repo.members): self.repo.members.append({"cluster_id":cid,"candidate_id":c.candidate_id,"candidate_version":c.candidate_version,"source_revision_id":c.source_revision_id,"anchor_ids":list(c.source_anchor_ids),"created_at":now()})
  independence=self._independence(members); relationships=self._relationships(rid,cid,members,independence); summary=self._summary(members,independence,relationships); values=sorted({self._value(c) for c in members}); aid=self.repo.next(); version_no=1+max((x["version"] for x in self.repo.versions if x["cluster_id"]==cid),default=0); prior=[x for x in self.repo.versions if x["cluster_id"]==cid and x["active"]]
  for x in prior: x["active"]=False; x["superseded_by_version_id"]=aid
  aggregate={"aggregate_id":cid,"aggregate_version_id":aid,"cluster_id":cid,"version":version_no,"aggregate_type":key[0],"candidate_type":members[0].candidate_type,"normalized_subject":key[1],"normalized_predicate":key[2],"normalized_object":values[0] if len(values)==1 else "MULTIPLE_VALUES","contributing_candidate_ids":[c.candidate_id for c in members],"contributing_candidate_version_ids":[f"{c.candidate_id}:{c.candidate_version}" for c in members],"source_revisions":sorted({c.source_revision_id for c in members}),"source_anchor_links":[{"candidate_id":c.candidate_id,"revision_id":c.source_revision_id,"anchor_ids":list(c.source_anchor_ids)} for c in members],"source_count":summary["independent_sources"],"document_count":len({c.source_document_id or str(c.source_revision_id) for c in members}),"evidence_type_distribution":dict(Counter(c.evidence_type for c in members)),"supporting_evidence_count":summary["supporting_assertions"],"contradictory_evidence_count":summary["contradicting_assertions"],"duplicate_evidence_count":summary["duplicate_assertions"],"unresolved_evidence_count":summary["unresolved_assertions"],"temporal_context":self._temporal(members),"geographic_context":self._geographic(members),"taxonomic_context":self._taxonomic(rid,cid,members),"measurement_summary":self._measurements(rid,cid,members),"aggregation_ruleset_version":self.ruleset,"reconciliation_model_version":self.model,"confidence_dimensions":summary,"uncertainty_dimensions":{"conflicts":summary["contradicting_assertions"],"independence_uncertain":sum(x["uncertainty"]>0 for x in independence),"taxon_ambiguity":sum(len(c.taxon_links)>1 for c in members)},"review_state":"REQUIRED","verification_state":"UNVERIFIED","aggregate_status":self._consensus(members,summary),"copyright_safe_display_state":self._display(members),"published":False,"active":True,"identity_hash":identity,"provenance_chain":{"candidate_versions":[f"{c.candidate_id}:{c.candidate_version}" for c in members],"ruleset":self.ruleset,"model":self.model},"created_at":now(),"updated_at":now(),"supersession_state":"CURRENT"}
  self.repo.aggregates.append(aggregate); self.repo.versions.append(aggregate); self.repo.evidence.extend(aggregate["source_anchor_links"]); self.repo.review(rid,"CONSENSUS_STATUS_AMBIGUITY",{"status":aggregate["aggregate_status"]},aggregate["contributing_candidate_ids"],cid); self.repo.runs[rid]["metrics"]["aggregates_created"]+=1; self.repo.runs[rid]["metrics"]["aggregate_versions_created"]+=1; self.repo.runs[rid]["metrics"]["processed_candidates"]+=len(members); item["state"]="COMPLETED"
 def _value(self,c):
  if c.numeric_value is not None and (c.unit or "").casefold() in UNIT_FACTORS: dim,factor=UNIT_FACTORS[(c.unit or "").casefold()]; return f"{c.numeric_value*factor:g}:{dim}:base"
  return norm(c.object_value if c.object_value is not None else c.numeric_value)
 def _independence(self,members):
  result=[]; seen_documents=set()
  for c in members:
   root=c.source_lineage or c.document_hash or c.source_document_id or str(c.source_revision_id); derivative=c.source_class in {"REVIEW","AI_SYNTHESIS","DATABASE_IMPORT","INTERNAL_DERIVATIVE"}; duplicate=bool(c.document_hash and c.document_hash in seen_documents); independent=not derivative and not duplicate; value={"candidate_id":c.candidate_id,"lineage_root":root,"independent":independent,"derivative":derivative or duplicate,"duplicate_document":duplicate,"shared_citation_lineage":list(c.citation_lineage),"uncertainty":.25 if not c.source_lineage and not c.document_hash else 0}; result.append(value); self.repo.independence.append(value)
   if c.document_hash: seen_documents.add(c.document_hash)
  return result
 def _relationships(self,rid,cid,members,independence):
  links=[]
  for i,left in enumerate(members):
   for right in members[i+1:]:
    same=self._value(left)==self._value(right); same_doc=bool(left.document_hash and left.document_hash==right.document_hash) or left.source_revision_id==right.source_revision_id
    if same_doc: rel=EvidenceRelationship.DUPLICATES
    elif same: rel=EvidenceRelationship.SUPPORTS
    elif left.geographic_context!=right.geographic_context and left.geographic_context and right.geographic_context: rel=EvidenceRelationship.GEOGRAPHICALLY_LIMITS
    elif left.temporal_context!=right.temporal_context and left.temporal_context and right.temporal_context: rel=EvidenceRelationship.QUALIFIES
    elif left.method_context!=right.method_context and left.method_context and right.method_context: rel=EvidenceRelationship.METHOD_DEPENDENT
    elif left.metadata.get("relationship_to",{}).get(str(right.candidate_id))=="CONTRADICTS" or right.metadata.get("relationship_to",{}).get(str(left.candidate_id))=="CONTRADICTS": rel=EvidenceRelationship.CONTRADICTS
    else: rel=EvidenceRelationship.UNRESOLVED_RELATIONSHIP
    link={"relationship_id":self.repo.next(),"cluster_id":cid,"source_candidate_id":left.candidate_id,"target_candidate_id":right.candidate_id,"relationship_type":rel.value,"rationale":f"classified by {self.ruleset}","ruleset_version":self.ruleset,"model_version":self.model,"confidence":1.0 if rel in {EvidenceRelationship.DUPLICATES,EvidenceRelationship.SUPPORTS} else .6,"review_state":"REQUIRED","source_anchor_ids":sorted(set(left.source_anchor_ids+right.source_anchor_ids)),"created_at":now(),"updated_at":now()}; links.append(link); self.repo.relationships.append(link)
    metric="support_links" if rel==EvidenceRelationship.SUPPORTS else "contradiction_links" if rel==EvidenceRelationship.CONTRADICTS else "duplicate_links" if rel==EvidenceRelationship.DUPLICATES else None
    if metric:self.repo.runs[rid]["metrics"][metric]+=1
    if rel in {EvidenceRelationship.CONTRADICTS,EvidenceRelationship.UNRESOLVED_RELATIONSHIP}:
     conflict=self.repo.next(); self.repo.conflicts[conflict]={"conflict_id":conflict,"cluster_id":cid,"candidate_ids":[left.candidate_id,right.candidate_id],"category":self._conflict_category(left,right),"incompatible_dimensions":["value"],"compatible_dimensions":["subject","predicate"],"possible_explanation":"context or evidence disagreement","unresolved_questions":["Which contexts are scientifically compatible?"],"reviewer_status":"OPEN","resolution_history":[],"source_anchor_ids":link["source_anchor_ids"]}; self.repo.runs[rid]["metrics"]["conflict_groups"]+=1; self.repo.review(rid,"CONTRADICTORY_EVIDENCE",{"conflict_id":conflict},[left.candidate_id,right.candidate_id],cid,"HIGH")
  return links
 def _conflict_category(self,a,b):
  if a.taxon_links!=b.taxon_links:return "TAXONOMIC"
  if a.numeric_value is not None:return "QUANTITATIVE"
  if a.geographic_context!=b.geographic_context:return "GEOGRAPHIC"
  if a.temporal_context!=b.temporal_context:return "TEMPORAL"
  if a.method_context!=b.method_context:return "METHODOLOGICAL"
  return "UNKNOWN"
 def _summary(self,members,independence,relationships):
  rel=Counter(x["relationship_type"] for x in relationships); independent_roots={x["lineage_root"] for x in independence if x["independent"]}; direct=Counter(c.directness for c in members); classes=Counter(c.source_class for c in members)
  return {"source_candidates":len(members),"independent_sources":len(independent_roots),"primary_sources":classes["PRIMARY"],"derivative_sources":sum(x["derivative"] for x in independence),"direct_observations":direct["DIRECT_OBSERVATION"],"experiments":classes["EXPERIMENT"],"statistical_results":sum(bool(c.measurement_context.get("statistics")) for c in members),"reviews":classes["REVIEW"],"ai_syntheses":classes["AI_SYNTHESIS"],"supporting_assertions":rel["SUPPORTS"],"contradicting_assertions":rel["CONTRADICTS"],"duplicate_assertions":rel["DUPLICATES"],"unresolved_assertions":rel["UNRESOLVED_RELATIONSHIP"],"source_reliability_distribution":dict(Counter("HIGH" if c.confidence>=.8 else "MEDIUM" if c.confidence>=.5 else "LOW" for c in members)),"evidence_directness_distribution":dict(direct),"anchor_completeness":sum(bool(c.source_anchor_ids) for c in members)/len(members),"taxon_link_certainty":sum(max((float(x.get("confidence",0)) for x in c.taxon_links),default=0) for c in members)/len(members),"temporal_compatibility":1.0 if len({digest(c.temporal_context) for c in members})<=1 else .5,"geographic_compatibility":1.0 if len({digest(c.geographic_context) for c in members})<=1 else .5,"method_compatibility":1.0 if len({digest(c.method_context) for c in members})<=1 else .5,"review_completeness":sum(c.review_state=="APPROVED" for c in members)/len(members),"prioritization_score_formula":"086b-priority-1","prioritization_score":round((len(independent_roots)+rel["SUPPORTS"])/(1+len(members)+rel["CONTRADICTS"]),4),"score_is_truth_probability":False}
 def _consensus(self,m,s):
  if any(len(c.taxon_links)>1 for c in m):return ConsensusStatus.TAXONOMICALLY_AMBIGUOUS.value
  if s["contradicting_assertions"]:return ConsensusStatus.CONFLICTING.value
  if s["unresolved_assertions"]:return ConsensusStatus.MIXED_EVIDENCE.value
  if s["independent_sources"]<=1:return ConsensusStatus.SINGLE_SOURCE.value
  if s["method_compatibility"]<1:return ConsensusStatus.METHOD_DEPENDENT.value
  if s["geographic_compatibility"]<1:return ConsensusStatus.GEOGRAPHICALLY_LIMITED.value
  if s["independent_sources"]>=3 and s["supporting_assertions"]>=2:return ConsensusStatus.STRONGLY_SUPPORTED.value
  return ConsensusStatus.SUPPORTED.value
 def _temporal(self,m):
  dates=[v for c in m for k,v in c.temporal_context.items() if "date" in k and v]; return {"contexts":[c.temporal_context for c in m],"earliest_evidence_date":min(dates) if dates else None,"latest_evidence_date":max(dates) if dates else None,"superseded_candidate_ids":[c.candidate_id for c in m if c.status in {"SUPERSEDED","RETRACTED","CORRECTED"}],"trend_conclusion":None}
 def _geographic(self,m): return {"contexts":[c.geographic_context for c in m],"scopes":sorted({str(c.geographic_context.get("region") or c.geographic_context.get("country") or "UNRESOLVED") for c in m}),"universalized":False}
 def _taxonomic(self,rid,cid,m):
  ambiguous=[c.candidate_id for c in m if len(c.taxon_links)!=1]
  if ambiguous:self.repo.review(rid,"AMBIGUOUS_TAXON_RECONCILIATION",{"candidate_ids":ambiguous},ambiguous,cid,"HIGH")
  return {"source_names":[c.metadata.get("source_name",c.normalized_subject) for c in m],"match_candidates":{str(c.candidate_id):list(c.taxon_links) for c in m},"canonical_rewrite_performed":False,"ambiguous_candidate_ids":ambiguous}
 def _measurements(self,rid,cid,m):
  numeric=[c for c in m if c.numeric_value is not None]; converted=[]
  for c in numeric:
   info=UNIT_FACTORS.get((c.unit or "").casefold()); converted.append({"candidate_id":c.candidate_id,"original_value":c.numeric_value,"original_unit":c.unit,"normalized_value":c.numeric_value*info[1] if info else None,"dimension":info[0] if info else None,"conversion_rule_version":"086b-units-1","sample_size":c.measurement_context.get("sample_size"),"method":c.method_context})
  compatible=bool(converted) and len({x["dimension"] for x in converted})==1 and len({digest(x["method"]) for x in converted})==1
  vals=[x["normalized_value"] for x in converted if x["normalized_value"] is not None]
  if numeric and not compatible:self.repo.review(rid,"INCOMPATIBLE_MEASUREMENTS",{"candidate_ids":[c.candidate_id for c in numeric]},[c.candidate_id for c in numeric],cid,"HIGH")
  return {"measurements":converted,"compatible":compatible,"observed_min":min(vals) if compatible else None,"observed_max":max(vals) if compatible else None,"unweighted_mean":sum(vals)/len(vals) if compatible and vals else None,"pooled_estimate":None,"pooled_estimate_prohibited":True,"independent_sample_size_total":sum(int(x["sample_size"] or 0) for x in converted) if compatible else None}
 def _display(self,m):
  states={c.display_policy for c in m}; return "METADATA_ONLY" if states&{"METADATA_ONLY","UNKNOWN_REQUIRES_REVIEW"} else "INTERNAL_RESEARCH_ONLY" if "INTERNAL_RESEARCH_ONLY" in states else "LIMITED_PREVIEW_ONLY" if "LIMITED_PREVIEW_ONLY" in states else "FULL_TEXT_ALLOWED"
 def cancel(self,rid):return self.repo.request_cancel(rid)
 def resume(self,rid):self.repo.clear_cancel(rid); self.repo.runs[rid]["metrics"]["retries"]+=1; return self.execute(rid)
 def retry(self,rid):return self.resume(rid)
 def supersede(self,aggregate_id,reason,actor,replacement=None):
  current=next(x for x in reversed(self.repo.versions) if x["aggregate_id"]==aggregate_id and x["active"]); current.update(active=False,aggregate_status="SUPERSEDED",supersession_state="SUPERSEDED"); value={"tombstone_id":self.repo.next(),"aggregate_id":aggregate_id,"aggregate_version_id":current["aggregate_version_id"],"reason":reason,"effective_at":now(),"replacement_aggregate_id":replacement,"actor":actor,"audit_metadata":{}}; self.repo.tombstones.append(value); return value
