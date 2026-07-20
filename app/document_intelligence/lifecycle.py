from __future__ import annotations
import hashlib, json
from typing import Any
from .adapters import ADAPTERS
from .classifier import classify

TRANSITIONS={"PENDING":{"CLASSIFYING","CANCELLED"},"CLASSIFYING":{"CLASSIFIED","PARTIAL","FAILED","CANCELLED"},"CLASSIFIED":{"EXTRACTING","CANCELLED"},"EXTRACTING":{"STRUCTURED","PARTIAL","FAILED","CANCELLED"},"STRUCTURED":{"DERIVING_OBJECTS","PARTIAL","CANCELLED"},"DERIVING_OBJECTS":{"READY_FOR_REVIEW","PARTIAL","FAILED","CANCELLED"},"PARTIAL":{"CLASSIFYING","EXTRACTING","STRUCTURED","DERIVING_OBJECTS","CANCELLED"},"READY_FOR_REVIEW":{"COMPLETED","CANCELLED"},"COMPLETED":set(),"FAILED":{"CLASSIFYING","EXTRACTING","DERIVING_OBJECTS","CANCELLED"},"CANCELLED":set()}

def configuration_hash(configuration:dict[str,Any])->str:
    return hashlib.sha256(json.dumps(configuration,sort_keys=True,separators=(",",":")).encode()).hexdigest()

class ExtractionService:
    def __init__(self,repository:Any): self.repository=repository
    def start(self,revision_id:int,extractor_version:str,ruleset_version:str,configuration:dict[str,Any]|None=None):
        configuration=configuration or {}; source=self.repository.source_revision(revision_id); record=self.repository.ensure_record(source)
        run=self.repository.ensure_run(record["record_id"],extractor_version,ruleset_version,configuration_hash(configuration))
        if run["state"]=="COMPLETED": return run
        return self._process(run,source,ruleset_version)
    def resume(self,run_id:int):
        run=self.repository.run(run_id); return self._process(run,self.repository.source_revision_for_run(run_id),run["ruleset_version"])
    def cancel(self,run_id:int): return self.repository.cancel(run_id)
    def _move(self,run,target):
        if target not in TRANSITIONS[run["state"]]: raise ValueError(f"INVALID_EXTRACTION_TRANSITION:{run['state']}->{target}")
        run=self.repository.transition(run["extraction_run_id"],target); return run
    def _process(self,run,source,ruleset):
        try:
            if self.repository.cancel_requested(run["extraction_run_id"]): return self.repository.transition(run["extraction_run_id"],"CANCELLED")
            if run["state"] in {"PENDING","FAILED","PARTIAL"}:
                run=self._move(run,"CLASSIFYING"); c=classify(source["filename"],source.get("text_hint","") or "",version=ruleset); self.repository.classify(run["record_id"],c); run=self._move(run,"CLASSIFIED")
            run=self._move(run,"EXTRACTING"); adapter=ADAPTERS.get(source["mime_type"])
            if not adapter: raise ValueError("UNSUPPORTED_EXTRACTION_FORMAT")
            document=adapter.extract(source["content"]); self.repository.persist_intermediate(run["extraction_run_id"],source["revision_id"],adapter.__class__.__name__,adapter.version,document)
            if self.repository.cancel_requested(run["extraction_run_id"]): return self.repository.transition(run["extraction_run_id"],"CANCELLED")
            run=self._move(run,"STRUCTURED"); run=self._move(run,"DERIVING_OBJECTS"); self.repository.create_chunks(run["extraction_run_id"]); run=self._move(run,"READY_FOR_REVIEW"); return self._move(run,"COMPLETED")
        except Exception as exc:
            self.repository.warning(run["extraction_run_id"],exc.__class__.__name__,str(exc)); target="PARTIAL" if self.repository.has_structures(run["extraction_run_id"]) else "FAILED"
            return self.repository.transition(run["extraction_run_id"],target)
