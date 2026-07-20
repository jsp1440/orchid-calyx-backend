from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.security import verify_owner_or_api_key
from .scientific import STORE

router=APIRouter(prefix="/api/document-intelligence",tags=["document-intelligence"])
protected=APIRouter(dependencies=[Depends(verify_owner_or_api_key)])
def actor(auth): return str(auth.get("actor") or auth.get("subject") or "operator")
class Start(BaseModel): revision_id:int=Field(gt=0); metadata:dict[str,Any]={}; text:str=""
class BatchStart(BaseModel): documents:list[Start]=Field(min_length=1,max_length=100)
class Override(BaseModel): document_class:str; reason:str=Field(min_length=1)
class Resolution(BaseModel): decision:str; rationale:str=Field(min_length=1)

@protected.post("/extractions",status_code=201)
def start(p:Start): return STORE.register(p.revision_id,p.metadata,p.text)
@protected.post("/extractions/batch",status_code=201)
def start_batch(p:BatchStart): return {"items":[STORE.register(x.revision_id,x.metadata,x.text) for x in p.documents]}
@router.get("/extractions/{rid}")
def status(rid:int): return STORE.extraction(rid)
@router.get("/records/{rid}/history")
def history(rid:int): return {"runs":[STORE.extraction(rid)],"classifications":STORE.classifications.get(rid,[]),"audit":[x for x in STORE.audit if x.get("record_id")==rid]}
@protected.post("/extractions/{rid}/resume")
def resume(rid:int): return STORE.resume(rid)
@protected.post("/extractions/{rid}/cancel")
def cancel(rid:int): return STORE.cancel(rid)
@router.get("/records/{rid}/classification")
def classification(rid:int): return STORE.classification(rid)
@router.get("/records/{rid}/assessment")
def assessment(rid:int): return STORE.assessments.get(rid,{})
@router.get("/records/{rid}/consumers")
def consumers(rid:int): return {"items":[x for x in STORE.consumers if x["record_id"]==rid]}
@router.get("/records/{rid}/outline")
def outline(rid:int): return {"items":[{"kind":kind,"object_id":oid} for kind,items in STORE.objects.items() for oid,value in items.items() if value["revision_id"]==rid]}
@protected.post("/records/{rid}/classification/override")
def override(rid:int,p:Override,auth:Annotated[dict,Depends(verify_owner_or_api_key)]): return STORE.override_classification(rid,p.document_class,p.reason,actor(auth))
@router.get("/{kind}/{oid}")
def read_object(kind:str,oid:int):
    try:return STORE.complete(kind,oid,authenticated=False)
    except KeyError as exc: raise HTTPException(404,"OBJECT_NOT_FOUND") from exc
@protected.get("/operator/{kind}/{oid}")
def read_object_operator(kind:str,oid:int): return STORE.complete(kind,oid,authenticated=True)
@router.get("/records/{rid}/{kind}")
def list_objects(rid:int,kind:str): return {"items":[STORE.complete(kind,oid) for oid,value in STORE.objects[kind].items() if value["revision_id"]==rid]}
@router.get("/extractions/{rid}/warnings")
def warnings(rid:int): return {"items":[]}
@protected.get("/reviews")
def reviews(): return {"items":list(STORE.reviews.values())}
@protected.post("/reviews/{review_id}/resolve")
def resolve(review_id:int,p:Resolution,auth:Annotated[dict,Depends(verify_owner_or_api_key)]): return STORE.resolve_review(review_id,p.decision,p.rationale,actor(auth))
router.include_router(protected)
