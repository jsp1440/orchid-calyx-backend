from __future__ import annotations
from typing import Annotated,Any
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from app.security import verify_owner_or_api_key
from .models import CandidateInput
from .repository import MemoryAggregateRepository
from .service import EvidenceAggregationService
router=APIRouter(prefix="/api/evidence-aggregation",tags=["evidence-aggregation"],dependencies=[Depends(verify_owner_or_api_key)])
REPOSITORY=MemoryAggregateRepository(); SERVICE=EvidenceAggregationService(REPOSITORY)
class CandidateIn(BaseModel):
 candidate_id:int=Field(gt=0); candidate_version:int=Field(gt=0); candidate_type:str; normalized_subject:str; predicate:str; object_value:str|None=None; numeric_value:float|None=None; unit:str|None=None; source_revision_id:int=Field(gt=0); source_document_id:str=""; source_anchor_ids:list[int]=Field(min_length=1); evidence_type:str="UNKNOWN"; source_class:str="UNKNOWN"; directness:str="INDIRECT"; source_lineage:str|None=None; citation_lineage:list[str]=[]; document_hash:str|None=None; taxon_links:list[dict[str,Any]]=[]; temporal_context:dict[str,Any]={}; geographic_context:dict[str,Any]={}; method_context:dict[str,Any]={}; population_context:dict[str,Any]={}; measurement_context:dict[str,Any]={}; confidence:float=.5; review_state:str="REQUIRED"; verification_state:str="UNVERIFIED"; status:str="ACTIVE"; display_policy:str="UNKNOWN_REQUIRES_REVIEW"; metadata:dict[str,Any]={}
class PreviewIn(BaseModel): candidates:list[CandidateIn]=Field(min_length=1,max_length=2000); filters:dict[str,Any]={}; policies:dict[str,str]={}
class Decision(BaseModel): action:str; rationale:str=Field(min_length=1)
class ClusterAction(BaseModel): cluster_ids:list[int]=Field(min_length=1); rationale:str=Field(min_length=1)
class SourceDecision(BaseModel): candidate_ids:list[int]=Field(min_length=1); dependence:str; rationale:str=Field(min_length=1)
class Supersede(BaseModel): reason:str=Field(min_length=1); replacement_aggregate_id:int|None=None
def candidate(v):
 d=v.model_dump();
 for key in ("source_anchor_ids","citation_lineage","taxon_links"):d[key]=tuple(d[key])
 return CandidateInput(**d)
@router.post("/preview",status_code=201)
def preview(p:PreviewIn):
 try:return SERVICE.preview([candidate(x) for x in p.candidates],p.filters,p.policies)
 except ValueError as e:raise HTTPException(422,str(e)) from e
@router.post("/runs/{rid}/execute")
def execute(rid:int):return SERVICE.execute(rid)
@router.get("/runs/{rid}")
def status(rid:int):return REPOSITORY.status(rid)
@router.post("/runs/{rid}/cancel")
def cancel(rid:int):return SERVICE.cancel(rid)
@router.post("/runs/{rid}/resume")
def resume(rid:int):return SERVICE.resume(rid)
@router.post("/runs/{rid}/retry")
def retry(rid:int):return SERVICE.retry(rid)
@router.get("/runs")
def history():return {"items":list(REPOSITORY.runs.values())}
@router.get("/runs/{rid}/items")
def items(rid:int):return {"items":REPOSITORY.items[rid],"warnings":[x for x in REPOSITORY.warnings if x.get("run_id")==rid]}
@router.get("/clusters")
def clusters(aggregate_type:str|None=None,review_state:str|None=None):return {"items":[x for x in REPOSITORY.clusters.values() if (not aggregate_type or x["aggregate_type"]==aggregate_type) and (not review_state or x["review_state"]==review_state)]}
@router.get("/clusters/{cid}")
def cluster(cid:int):return {**REPOSITORY.clusters[cid],"members":[x for x in REPOSITORY.members if x["cluster_id"]==cid]}
@router.post("/clusters/split")
def split(p:ClusterAction):return {"review":REPOSITORY.review(0,"SPLIT_CLUSTER_REQUESTED",p.model_dump(),cluster_id=p.cluster_ids[0])}
@router.post("/clusters/merge")
def merge(p:ClusterAction):return {"review":REPOSITORY.review(0,"MERGE_CLUSTERS_REQUESTED",p.model_dump(),cluster_id=p.cluster_ids[0])}
@router.get("/aggregates")
def aggregates(aggregate_type:str|None=None,status:str|None=None,review_state:str|None=None,conflict_state:str|None=None,minimum_confidence:float|None=None):
 values=[x for x in REPOSITORY.versions if x["active"]]; return {"items":[x for x in values if (not aggregate_type or x["aggregate_type"]==aggregate_type) and (not status or x["aggregate_status"]==status) and (not review_state or x["review_state"]==review_state)]}
@router.get("/aggregates/{aid}")
def aggregate(aid:int):return next(x for x in reversed(REPOSITORY.versions) if x["aggregate_id"]==aid and x["active"])
@router.get("/aggregates/{aid}/versions")
def versions(aid:int):return {"items":[x for x in REPOSITORY.versions if x["aggregate_id"]==aid]}
@router.get("/aggregates/{aid}/summary")
def summary(aid:int):return aggregate(aid)["confidence_dimensions"]
@router.get("/aggregates/{aid}/support-network")
def support(aid:int):return {"items":[x for x in REPOSITORY.relationships if x["cluster_id"]==aid and x["relationship_type"] in {"SUPPORTS","PARTIALLY_SUPPORTS","QUALIFIES","REFINES"}]}
@router.get("/aggregates/{aid}/contradiction-network")
def contradictions(aid:int):return {"items":[x for x in REPOSITORY.relationships if x["cluster_id"]==aid and x["relationship_type"] in {"CONTRADICTS","DOES_NOT_SUPPORT","UNRESOLVED_RELATIONSHIP"}]}
@router.get("/aggregates/{aid}/source-independence")
def independence(aid:int):return {"items":[x for x in REPOSITORY.independence if x["candidate_id"] in aggregate(aid)["contributing_candidate_ids"]]}
@router.get("/aggregates/{aid}/{dimension}")
def reconciliation(aid:int,dimension:str):
 key={"taxonomy":"taxonomic_context","temporal":"temporal_context","geographic":"geographic_context","measurements":"measurement_summary"}.get(dimension)
 if not key:raise HTTPException(404,"RECONCILIATION_DIMENSION_NOT_FOUND")
 return aggregate(aid)[key]
@router.get("/conflicts")
def conflicts():return {"items":list(REPOSITORY.conflicts.values())}
@router.get("/reviews")
def reviews(state:str="OPEN"):return {"items":[x for x in REPOSITORY.reviews.values() if x["state"]==state]}
@router.post("/reviews/{ident}/resolve")
def resolve(ident:int,p:Decision,auth:Annotated[dict,Depends(verify_owner_or_api_key)]):return REPOSITORY.resolve_review(ident,p.action,p.rationale,str(auth.get("actor") or auth.get("subject") or "operator"))
@router.post("/sources/dependence")
def source_dependence(p:SourceDecision):return {"review":REPOSITORY.review(0,"SOURCE_INDEPENDENCE_DECISION",p.model_dump(),p.candidate_ids)}
@router.post("/aggregates/{aid}/supersede")
def supersede(aid:int,p:Supersede,auth:Annotated[dict,Depends(verify_owner_or_api_key)]):return SERVICE.supersede(aid,p.reason,str(auth.get("actor") or "operator"),p.replacement_aggregate_id)
@router.post("/aggregates/{aid}/withdraw")
def withdraw(aid:int,p:Supersede,auth:Annotated[dict,Depends(verify_owner_or_api_key)]):return SERVICE.supersede(aid,"WITHDRAWN: "+p.reason,str(auth.get("actor") or "operator"),p.replacement_aggregate_id)
@router.get("/export")
def export():return {"items":[{k:v for k,v in x.items() if k not in {"authorized_quote","source_text","text"}} for x in REPOSITORY.versions if x["active"]],"review_safe":True}
@router.get("/registry")
def registry():return {"rulesets":REPOSITORY.rulesets,"models":REPOSITORY.models}
@router.get("/tombstones")
def tombstones():return {"items":REPOSITORY.tombstones}
@router.get("/health")
def health():return {"status":"ok","candidate_only":True,"publishes_graph":False,"network_required":False}
