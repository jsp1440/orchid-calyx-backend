from __future__ import annotations
from typing import Annotated,Any
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field
from app.security import verify_owner_or_api_key
from .models import CandidateInput
from .repository import MemoryAggregateRepository
from .service import EvidenceAggregationService
from app.persistence.state_repository import configured_database_url
router=APIRouter(prefix="/api/evidence-aggregation",tags=["evidence-aggregation"],dependencies=[Depends(verify_owner_or_api_key)])
def _build_repository():
 if configured_database_url():
  from .postgres_repository import PostgresAggregateRepository
  return PostgresAggregateRepository()
 return MemoryAggregateRepository()
try:REPOSITORY=_build_repository();REPOSITORY_ERROR=None
except Exception:REPOSITORY=None;REPOSITORY_ERROR="AGGREGATION_DATABASE_UNAVAILABLE"
SERVICE=EvidenceAggregationService(REPOSITORY) if REPOSITORY is not None else None
def _available():
 if REPOSITORY is None or SERVICE is None:raise HTTPException(503,detail={"code":REPOSITORY_ERROR or "AGGREGATION_DATABASE_UNAVAILABLE"})
 return REPOSITORY,SERVICE
def _write(operation):
 repository,_=_available()
 try:return repository.atomic(operation) if hasattr(repository,"atomic") else operation()
 except HTTPException:raise
 except Exception as exc:raise HTTPException(503,detail={"code":"AGGREGATION_DATABASE_UNAVAILABLE"}) from exc
def _read():
 repository,_=_available()
 try:
  if hasattr(repository,"refresh"):repository.refresh()
  return repository
 except Exception as exc:raise HTTPException(503,detail={"code":"AGGREGATION_DATABASE_UNAVAILABLE"}) from exc
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
 try:
  _,service=_available();return _write(lambda:service.preview([candidate(x) for x in p.candidates],p.filters,p.policies))
 except ValueError as e:raise HTTPException(422,str(e)) from e
@router.post("/runs/{rid}/execute")
def execute(rid:int):
 _,service=_available()
 try:return _write(lambda:service.execute(rid))
 except KeyError as exc:raise HTTPException(404,detail={"code":"AGGREGATE_RUN_NOT_FOUND"}) from exc
@router.get("/runs/{rid}")
def status(rid:int):
 try:return _read().status(rid)
 except KeyError as exc:raise HTTPException(404,detail={"code":"AGGREGATE_RUN_NOT_FOUND"}) from exc
@router.post("/runs/{rid}/cancel")
def cancel(rid:int):
 _,service=_available()
 try:return _write(lambda:service.cancel(rid))
 except KeyError as exc:raise HTTPException(404,detail={"code":"AGGREGATE_RUN_NOT_FOUND"}) from exc
@router.post("/runs/{rid}/resume")
def resume(rid:int):
 _,service=_available()
 try:return _write(lambda:service.resume(rid))
 except KeyError as exc:raise HTTPException(404,detail={"code":"AGGREGATE_RUN_NOT_FOUND"}) from exc
@router.post("/runs/{rid}/retry")
def retry(rid:int):
 _,service=_available()
 try:return _write(lambda:service.retry(rid))
 except KeyError as exc:raise HTTPException(404,detail={"code":"AGGREGATE_RUN_NOT_FOUND"}) from exc
@router.get("/runs")
def history(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
 values=sorted(_read().runs.values(),key=lambda x:x["aggregate_run_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}
@router.get("/runs/{rid}/items")
def items(rid:int,limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0,le=10000)):
 repository=_read()
 if rid not in repository.items:raise HTTPException(404,detail={"code":"AGGREGATE_RUN_NOT_FOUND"})
 values=sorted(repository.items[rid],key=lambda x:x["item_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset,"warnings":[x for x in repository.warnings if x.get("run_id")==rid]}
@router.get("/clusters")
def clusters(aggregate_type:str|None=None,review_state:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
 values=sorted([x for x in _read().clusters.values() if (not aggregate_type or x["aggregate_type"]==aggregate_type) and (not review_state or x["review_state"]==review_state)],key=lambda x:x["cluster_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}
@router.get("/clusters/{cid}")
def cluster(cid:int):
 repository=_read()
 if cid not in repository.clusters:raise HTTPException(404,detail={"code":"CLUSTER_NOT_FOUND"})
 return {**repository.clusters[cid],"members":sorted([x for x in repository.members if x["cluster_id"]==cid],key=lambda x:(x["candidate_id"],x["candidate_version"]))}
@router.post("/clusters/split")
def split(p:ClusterAction):
 repository,_=_available();return _write(lambda:{"review":repository.review(0,"SPLIT_CLUSTER_REQUESTED",p.model_dump(),cluster_id=p.cluster_ids[0])})
@router.post("/clusters/merge")
def merge(p:ClusterAction):
 repository,_=_available();return _write(lambda:{"review":repository.review(0,"MERGE_CLUSTERS_REQUESTED",p.model_dump(),cluster_id=p.cluster_ids[0])})
@router.get("/aggregates")
def aggregates(aggregate_type:str|None=None,status:str|None=None,review_state:str|None=None,conflict_state:str|None=None,minimum_confidence:float|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
 values=[x for x in _read().versions if x["active"]];values=sorted([x for x in values if (not aggregate_type or x["aggregate_type"]==aggregate_type) and (not status or x["aggregate_status"]==status) and (not review_state or x["review_state"]==review_state)],key=lambda x:(x["aggregate_id"],x["version"]));return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}
@router.get("/aggregates/{aid}")
def aggregate(aid:int):
 value=next((x for x in reversed(_read().versions) if x["aggregate_id"]==aid and x["active"]),None)
 if value is None:raise HTTPException(404,detail={"code":"AGGREGATE_NOT_FOUND"})
 return value
@router.get("/aggregates/{aid}/versions")
def versions(aid:int):
 values=sorted([x for x in _read().versions if x["aggregate_id"]==aid],key=lambda x:x["version"])
 if not values:raise HTTPException(404,detail={"code":"AGGREGATE_NOT_FOUND"})
 return {"items":values}
@router.get("/aggregates/{aid}/summary")
def summary(aid:int):return aggregate(aid)["confidence_dimensions"]
@router.get("/aggregates/{aid}/support-network")
def support(aid:int):return {"items":sorted([x for x in _read().relationships if x["cluster_id"]==aid and x["relationship_type"] in {"SUPPORTS","PARTIALLY_SUPPORTS","QUALIFIES","REFINES"}],key=lambda x:x["relationship_id"])}
@router.get("/aggregates/{aid}/contradiction-network")
def contradictions(aid:int):return {"items":sorted([x for x in _read().relationships if x["cluster_id"]==aid and x["relationship_type"] in {"CONTRADICTS","DOES_NOT_SUPPORT","UNRESOLVED_RELATIONSHIP"}],key=lambda x:x["relationship_id"])}
@router.get("/aggregates/{aid}/source-independence")
def independence(aid:int):return {"items":sorted([x for x in _read().independence if x["candidate_id"] in aggregate(aid)["contributing_candidate_ids"]],key=lambda x:x["candidate_id"])}
@router.get("/aggregates/{aid}/{dimension}")
def reconciliation(aid:int,dimension:str):
 key={"taxonomy":"taxonomic_context","temporal":"temporal_context","geographic":"geographic_context","measurements":"measurement_summary"}.get(dimension)
 if not key:raise HTTPException(404,"RECONCILIATION_DIMENSION_NOT_FOUND")
 return aggregate(aid)[key]
@router.get("/conflicts")
def conflicts(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
 values=sorted(_read().conflicts.values(),key=lambda x:x["conflict_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}
@router.get("/reviews")
def reviews(state:str="OPEN",limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
 values=sorted([x for x in _read().reviews.values() if x["state"]==state],key=lambda x:x["review_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}
@router.post("/reviews/{ident}/resolve")
def resolve(ident:int,p:Decision,auth:Annotated[dict,Depends(verify_owner_or_api_key)]):
 repository,_=_available()
 if ident not in repository.reviews:raise HTTPException(404,detail={"code":"REVIEW_NOT_FOUND"})
 return _write(lambda:repository.resolve_review(ident,p.action,p.rationale,str(auth.get("actor") or auth.get("subject") or "operator")))
@router.post("/sources/dependence")
def source_dependence(p:SourceDecision):
 repository,_=_available();return _write(lambda:{"review":repository.review(0,"SOURCE_INDEPENDENCE_DECISION",p.model_dump(),p.candidate_ids)})
@router.post("/aggregates/{aid}/supersede")
def supersede(aid:int,p:Supersede,auth:Annotated[dict,Depends(verify_owner_or_api_key)]):
 _,service=_available();return _write(lambda:service.supersede(aid,p.reason,str(auth.get("actor") or "operator"),p.replacement_aggregate_id))
@router.post("/aggregates/{aid}/withdraw")
def withdraw(aid:int,p:Supersede,auth:Annotated[dict,Depends(verify_owner_or_api_key)]):
 _,service=_available();return _write(lambda:service.supersede(aid,"WITHDRAWN: "+p.reason,str(auth.get("actor") or "operator"),p.replacement_aggregate_id))
@router.get("/export")
def export():return {"items":[{k:v for k,v in x.items() if k not in {"authorized_quote","source_text","text"}} for x in sorted(_read().versions,key=lambda x:(x["aggregate_id"],x["version"])) if x["active"]],"review_safe":True}
@router.get("/registry")
def registry():
 repository=_read();return {"rulesets":repository.rulesets,"models":repository.models}
@router.get("/tombstones")
def tombstones(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
 values=sorted(_read().tombstones,key=lambda x:x["tombstone_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}
@router.get("/health")
def health():return {"status":"ok","candidate_only":True,"publishes_graph":False,"network_required":False,"persistent":hasattr(_read(),"atomic")}
