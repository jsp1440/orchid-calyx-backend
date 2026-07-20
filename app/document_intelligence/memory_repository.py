from __future__ import annotations
from dataclasses import asdict
class MemoryRepository:
    def __init__(self,sources): self.sources={s["revision_id"]:s for s in sources}; self.records={}; self.runs={}; self.classifications=[]; self.structures=[]; self.anchors=[]; self.chunks=[]; self.warnings=[]; self.next_run=1; self.cancelled=set()
    def source_revision(self,rid): return self.sources[rid]
    def source_revision_for_run(self,run_id): return self.sources[self.runs[run_id]["revision_id"]]
    def ensure_record(self,source): return self.records.setdefault(source["revision_id"],{"record_id":source["revision_id"],**source})
    def ensure_run(self,record_id,extractor,ruleset,config):
        for run in self.runs.values():
            if (run["record_id"],run["extractor_version"],run["ruleset_version"],run["configuration_hash"])==(record_id,extractor,ruleset,config): return run
        rid=self.next_run; self.next_run+=1; self.runs[rid]={"extraction_run_id":rid,"record_id":record_id,"revision_id":record_id,"extractor_version":extractor,"ruleset_version":ruleset,"configuration_hash":config,"state":"PENDING"}; return self.runs[rid]
    def run(self,rid): return self.runs[rid]
    def transition(self,rid,state): self.runs[rid]["state"]=state; return self.runs[rid]
    def classify(self,record_id,value): self.classifications.append({"record_id":record_id,**asdict(value)})
    def persist_intermediate(self,run_id,revision_id,adapter,version,doc):
        for block in doc.blocks:
            sid=len(self.structures)+1; self.structures.append({"structural_id":sid,"run_id":run_id,"complete_text":block.text,"kind":block.kind,"sequence":block.sequence,"level":block.heading_level}); self.anchors.append({"run_id":run_id,"revision_id":revision_id,"structural_id":sid,**asdict(block.anchor),"adapter":adapter,"version":version})
        for warning in doc.warnings: self.warning(run_id,"ADAPTER_WARNING",warning)
    def create_chunks(self,run_id):
        for s in self.structures:
            if s["run_id"]==run_id and s["complete_text"]: self.chunks.append({"run_id":run_id,"structural_id":s["structural_id"],"text":s["complete_text"],"complete_object_pointer":{"structural_id":s["structural_id"]}})
    def warning(self,run_id,code,message): self.warnings.append({"run_id":run_id,"code":code,"message":message})
    def has_structures(self,run_id): return any(s["run_id"]==run_id for s in self.structures)
    def cancel_requested(self,run_id): return run_id in self.cancelled
    def request_cancel(self,run_id): self.cancelled.add(run_id); return self.runs[run_id]
    def cancel(self,run_id): self.cancelled.add(run_id); return self.transition(run_id,"CANCELLED")
    def history(self,record_id): return [r for r in self.runs.values() if r["record_id"]==record_id]
