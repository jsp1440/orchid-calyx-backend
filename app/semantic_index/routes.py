from typing import Annotated,Any
from fastapi import APIRouter,Depends
from pydantic import BaseModel,Field
from app.security import verify_owner_or_api_key
from .memory_repository import MemoryIndexRepository
from .models import IndexDocument
from .provider import DeterministicLocalProvider
from .service import SemanticIndexService
router=APIRouter(prefix="/api/semantic-index",tags=["semantic-index"],dependencies=[Depends(verify_owner_or_api_key)])
REPO=MemoryIndexRepository(); SERVICE=SemanticIndexService(REPO,DeterministicLocalProvider())
class DocumentIn(BaseModel): source_object_type:str; source_object_id:int; revision_id:int; extraction_run_id:int; text:str; parent_type:str|None=None; parent_id:int|None=None; source_anchor_ids:list[int]=[]; internal_indexing_permission:bool=False; display_policy:str="UNKNOWN_REQUIRES_REVIEW"; metadata:dict[str,Any]={}
class PreviewIn(BaseModel): documents:list[DocumentIn]=Field(min_length=1,max_length=500); configuration:dict[str,Any]={}
@router.post("/preview",status_code=201)
def preview(p:PreviewIn): return SERVICE.preview([IndexDocument(**{**x.model_dump(),"source_anchor_ids":tuple(x.source_anchor_ids)}) for x in p.documents],configuration=p.configuration)
@router.post("/runs/{run_id}/execute")
def execute(run_id:int): return SERVICE.execute(run_id)
@router.get("/runs/{run_id}")
def status(run_id:int): return REPO.status(run_id)
@router.post("/runs/{run_id}/cancel")
def cancel(run_id:int): return SERVICE.cancel(run_id)
@router.post("/runs/{run_id}/resume")
def resume(run_id:int): return SERVICE.resume(run_id)
@router.get("/history")
def history(): return {"items":list(REPO.runs.values())}
@router.get("/runs/{run_id}/items")
def items(run_id:int): return {"items":REPO.items[run_id],"warnings":REPO.warnings}
@router.get("/registry")
def registry(): return {"models":REPO.models}
@router.get("/reviews")
def reviews(): return {"items":REPO.reviews}
@router.get("/sources/{object_type}/{object_id}/versions")
def versions(object_type:str,object_id:int): return {"items":[x for x in REPO.documents if x["source_object_type"]==object_type and x["source_object_id"]==object_id]}
@router.get("/tombstones")
def tombstones(): return {"items":REPO.tombstones}
