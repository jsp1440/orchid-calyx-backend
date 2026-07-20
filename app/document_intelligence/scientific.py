from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .classifier import classify

def now(): return datetime.now(timezone.utc).isoformat()

class DisplayPolicy(StrEnum):
    FULL_TEXT_ALLOWED="FULL_TEXT_ALLOWED"; LIMITED_PREVIEW_ONLY="LIMITED_PREVIEW_ONLY"; METADATA_ONLY="METADATA_ONLY"; INTERNAL_RESEARCH_ONLY="INTERNAL_RESEARCH_ONLY"; UNKNOWN_REQUIRES_REVIEW="UNKNOWN_REQUIRES_REVIEW"

CONSUMERS={"KNOWLEDGE_GRAPH","SPECIES_ATLAS","IDENTIFICATION_MATRIX","ILLUSTRATED_GLOSSARY","ORCHID_CONTINUUM_UNIVERSITY","CONSERVATION_PLATFORM","RESEARCH_PLATFORM","CALYX_EXPERIMENT_DESIGN","HOMEPAGE","NEWS_AND_INTELLIGENCE","GRANT_DEVELOPMENT","PARTNERSHIP_DEVELOPMENT","VISION_LAB","COLLECTION_MANAGEMENT","INTERNAL_OPERATIONS","API","OTHER"}
CLAIM_TYPES={"DIRECTLY_STATED_FACT","MEASUREMENT","AUTHOR_INTERPRETATION","RECOMMENDATION","HYPOTHESIS","MACHINE_INFERENCE","AI_GENERATED_SYNTHESIS","OPERATOR_ANNOTATION"}

class IntelligenceStore:
    """Deterministic reference repository; PostgreSQL uses the same persisted shapes."""
    def __init__(self):
        self.records={}; self.runs={}; self.classifications={}; self.assessments={}; self.consumers=[]; self.objects={k:{} for k in ("protocols","results","treatments","keys","media","tables","insights","events","claims")}; self.reviews={}; self.audit=[]; self._id=1
    def _next(self): value=self._id; self._id+=1; return value
    def register(self,revision_id:int,metadata:dict[str,Any],text:str=""):
        record={"record_id":revision_id,"revision_id":revision_id,"metadata":deepcopy(metadata),"text":text,"display_policy":metadata.get("display_policy",DisplayPolicy.UNKNOWN_REQUIRES_REVIEW),"created_at":now()}; self.records.setdefault(revision_id,record); self.runs.setdefault(revision_id,{"extraction_run_id":revision_id,"revision_id":revision_id,"state":"COMPLETED","created_at":now()})
        c=classify(metadata.get("title",metadata.get("filename","")),text); self.classifications.setdefault(revision_id,[{**c.__dict__,"document_class":c.document_class.value,"created_at":now(),"operator_override":False}])
        if c.confidence < .6: self.review(revision_id,"UNCERTAIN_CLASSIFICATION","MEDIUM",{"confidence":c.confidence})
        if record["display_policy"]==DisplayPolicy.UNKNOWN_REQUIRES_REVIEW: self.review(revision_id,"COPYRIGHT_DISPLAY_UNCERTAINTY","HIGH",{})
        return deepcopy(record)
    def extraction(self,rid): return deepcopy(self.runs[rid])
    def cancel(self,rid): self.runs[rid]["state"]="CANCELLED"; self.runs[rid]["cancelled_at"]=now(); return self.extraction(rid)
    def resume(self,rid): self.runs[rid]["state"]="COMPLETED"; self.runs[rid]["resumed_at"]=now(); return self.extraction(rid)
    def classification(self,rid): return deepcopy(self.classifications[rid][-1])
    def override_classification(self,rid,value,reason,actor):
        if not reason.strip(): raise ValueError("OVERRIDE_REASON_REQUIRED")
        entry={**self.classification(rid),"document_class":value,"operator_override":True,"override_reason":reason,"override_actor":actor,"override_at":now()}; self.classifications[rid].append(entry); self.audit.append({"action":"CLASSIFICATION_OVERRIDE","record_id":rid,"actor":actor,"reason":reason,"at":now()}); return deepcopy(entry)
    def assess(self,rid,**values):
        allowed={"YES","NO","UNKNOWN"}; ai={"YES","NO","PARTIAL","UNKNOWN"}; citations={"YES","NO","PARTIAL"}; temporal={"PERMANENT_CANON","CURRENT_REFERENCE","TIME_SENSITIVE","HISTORICAL","SUPERSEDED","UNKNOWN"}
        if values.get("peer_reviewed","UNKNOWN") not in allowed or values.get("ai_generated","UNKNOWN") not in ai or values.get("citations_verified","NO") not in citations or values.get("temporal_status","UNKNOWN") not in temporal: raise ValueError("INVALID_ASSESSMENT_ENUM")
        if "truth_score" in values: raise ValueError("UNIVERSAL_TRUTH_SCORE_PROHIBITED")
        result={"record_id":rid,"peer_reviewed":"UNKNOWN","ai_generated":"UNKNOWN","human_reviewed":"UNKNOWN","citations_supplied":"NO","citations_verified":"NO","reliability_assessment":{},"reliability_rationale":"","temporal_status":"UNKNOWN","created_at":now(),**values}; self.assessments[rid]=result; return deepcopy(result)
    def assign_consumer(self,rid,consumer,confidence,rationale,method="MACHINE_SUGGESTED",actor=None):
        if consumer not in CONSUMERS: raise ValueError("INVALID_CONSUMER")
        value={"assignment_id":self._next(),"record_id":rid,"consumer":consumer,"confidence":confidence,"rationale":rationale,"method":method,"operator_override":bool(actor),"actor":actor,"created_at":now()}; self.consumers.append(value); return deepcopy(value)
    def add_object(self,kind,rid,payload):
        if kind not in self.objects: raise ValueError("INVALID_OBJECT_KIND")
        oid=self._next(); value={f"{kind[:-1]}_id":oid,"object_id":oid,"revision_id":rid,"published":False,"created_at":now(),**deepcopy(payload)}
        anchors=value.get("source_anchors",[])
        if kind in {"protocols","results","treatments","keys","insights","claims"} and not anchors: raise ValueError("SOURCE_ANCHORS_REQUIRED")
        if kind=="claims" and value.get("claim_type") not in CLAIM_TYPES: raise ValueError("INVALID_CLAIM_TYPE")
        self.objects[kind][oid]=value; return deepcopy(value)
    def complete(self,kind,oid,*,authenticated=False):
        value=deepcopy(self.objects[kind][oid]); record=self.records[value["revision_id"]]; policy=DisplayPolicy(record["display_policy"])
        may_show=policy==DisplayPolicy.FULL_TEXT_ALLOWED or (authenticated and policy==DisplayPolicy.INTERNAL_RESEARCH_ONLY)
        if not may_show:
            for key in ("complete_text","text","claim_text","original_wording","ordered_sections"): value.pop(key,None)
            if policy==DisplayPolicy.LIMITED_PREVIEW_ONLY and record.get("text"): value["preview"]=record["text"][:int(record["metadata"].get("excerpt_limit",240))]
        value.update(display_policy=policy.value,license=record["metadata"].get("license"),attribution_requirements=record["metadata"].get("attribution_requirements"),public_display_permission=bool(record["metadata"].get("public_display_permission",policy==DisplayPolicy.FULL_TEXT_ALLOWED)))
        return value
    def review(self,rid,category,severity,evidence,object_id=None,anchors=None):
        ident=self._next(); value={"review_id":ident,"record_id":rid,"category":category,"severity":severity,"affected_object_id":object_id,"source_anchors":anchors or [],"evidence":deepcopy(evidence),"status":"OPEN","created_at":now()}; self.reviews[ident]=value; return deepcopy(value)
    def resolve_review(self,ident,decision,rationale,actor):
        if not rationale.strip(): raise ValueError("DECISION_RATIONALE_REQUIRED")
        value=self.reviews[ident]; value.update(status="RESOLVED",operator_decision=decision,decision_rationale=rationale,assigned_operator=actor,resolved_at=now()); self.audit.append({"action":"REVIEW_RESOLVED","review_id":ident,"actor":actor,"at":now()}); return deepcopy(value)

STORE=IntelligenceStore()
