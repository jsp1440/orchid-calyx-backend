from __future__ import annotations
import math,time,uuid
from collections import defaultdict
from dataclasses import asdict
from .models import RetrievalQuery
def cosine(a,b):
 if len(a)!=len(b): raise ValueError("QUERY_VECTOR_DIMENSION_MISMATCH")
 na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(x*x for x in b)); return sum(x*y for x,y in zip(a,b))/(na*nb) if na and nb else 0
class RetrievalEngine:
 def __init__(self,repository,provider,parents=None,ranking_version="085b-rank-1"): self.repo=repository; self.provider=provider; self.parents=parents or {}; self.ranking_version=ranking_version
 def search(self,q:RetrievalQuery):
  started=time.perf_counter(); terms=q.text.casefold().split(); query_vector=self.provider.embed_batch([q.text])[0] if q.mode in {"SEMANTIC","HYBRID"} else None; candidates=[]; excluded=defaultdict(int)
  for d in self.repo.documents:
   if q.active_only and not d.get("active",False): continue
   meta=d.get("metadata",{}); lexical=next((x for x in self.repo.lexical if x["index_document_id"]==d["index_document_id"]),{}); text=lexical.get("normalized_text",""); title=(lexical.get("title") or "").casefold()
   if q.collections and not set(q.collections)&set(meta.get("collections",[])): continue
   if q.object_types and d["source_object_type"] not in q.object_types: continue
   if q.document_classes and meta.get("document_class") not in q.document_classes: continue
   if q.language and lexical.get("language")!=q.language: continue
   if meta.get("tombstoned") or (meta.get("temporal_status") in {"SUPERSEDED","RETRACTED"} and not q.historical): excluded["STATUS"]+=1; continue
   if meta.get("expires_at") and meta["expires_at"]<meta.get("as_of","9999") and not q.historical: excluded["EXPIRED"]+=1; continue
   matches=[t for t in terms if t in text or t in title]; ls=(sum(text.count(t) for t in terms)+3*sum(title.count(t) for t in terms))/max(1,len(terms)); vector=next((v for v in self.repo.vectors if v["index_document_id"]==d["index_document_id"] and v.get("active",True)),None); ss=cosine(query_vector,vector["vector"]) if query_vector is not None and vector else 0
   if q.mode=="LEXICAL" and not matches: continue
   if q.mode=="SEMANTIC" and not vector: continue
   reliability=self._reliability(meta); temporal=self._temporal(meta); verification=.05 if meta.get("verification_state")=="VERIFIED" else 0; fused=(ls if q.mode=="LEXICAL" else ss if q.mode=="SEMANTIC" else .55*min(1,ls/4)+.45*max(0,ss))+reliability+temporal+verification
   candidates.append((fused,d,lexical,matches,{"lexical":ls,"semantic":ss,"reliability":reliability,"temporal":temporal,"verification":verification}))
  candidates.sort(key=lambda x:(-x[0],x[1]["index_document_id"])); seen_hash=set(); per_source=defaultdict(int); results=[]; deduped=0
  for fused,d,lexical,matches,scores in candidates:
   if d["content_hash"] in seen_hash: deduped+=1; continue
   if per_source[d["revision_id"]]>=q.per_source_limit: deduped+=1; continue
   seen_hash.add(d["content_hash"]); per_source[d["revision_id"]]+=1; results.append(self._assemble(q,d,lexical,matches,scores,fused,len(results)+1))
  page=results[q.offset:q.offset+q.limit]
  return {"normalized_query":q.text,"applied_filters":asdict(q),"retrieval_mode":q.mode,"active_collections":list(q.collections),"query_model":self.provider.metadata if query_vector is not None else None,"ranking_configuration_version":self.ranking_version,"total_candidates":len(candidates),"total_eligible_results":len(results),"excluded_counts":dict(excluded),"deduplicated_count":deduped,"results":page,"warnings":[],"elapsed_ms":round((time.perf_counter()-started)*1000,3)}
 def _reliability(self,m):
  value=0
  if m.get("peer_reviewed")=="YES": value+=.06
  if m.get("evidence_type")=="PRIMARY": value+=.05
  if m.get("ai_generated") in {"YES","PARTIAL"}: value-=.03
  if m.get("citations_verified")=="YES": value+=.04
  return value
 def _temporal(self,m): return .05 if m.get("temporal_status")=="TIME_SENSITIVE" and m.get("current",False) else 0
 def _assemble(self,q,d,l,matches,scores,fused,rank):
  meta=d.get("metadata",{}); policy=meta.get("display_policy","UNKNOWN_REQUIRES_REVIEW"); text=l.get("normalized_text",""); excerpt=None
  if policy=="FULL_TEXT_ALLOWED" or (policy=="INTERNAL_RESEARCH_ONLY" and q.internal_access and meta.get("internal_access_allowed",False)): excerpt=text
  elif policy=="LIMITED_PREVIEW_ONLY": excerpt=text[:int(meta.get("excerpt_limit",160))]
  parent=self.parents.get((d.get("parent_type"),d.get("parent_id"))) or self.parents.get((d["source_object_type"],d.get("parent_id")))
  expansion=self._expand(q,policy,parent,d)
  locator=meta.get("locator")
  return {"result_id":str(uuid.uuid5(uuid.NAMESPACE_URL,f"{d['index_document_id']}:{self.ranking_version}")),"rank":rank,"fused_score":round(fused,6),"score_breakdown":scores,"ranking_explanation":[f"lexical={scores['lexical']:.4f}",f"semantic={scores['semantic']:.4f}",f"reliability_adjustment={scores['reliability']:.4f}",f"temporal_adjustment={scores['temporal']:.4f}"],"object_type":d["source_object_type"],"title":l.get("title") or meta.get("title"),"authorized_excerpt":excerpt,"matched_terms":matches if excerpt is not None else [],"canonical_parent":{"type":d.get("parent_type") or d["source_object_type"],"id":d.get("parent_id"),"available":parent is not None},"parent_expansion":expansion,"complete_object":bool(expansion and expansion.get("complete_object")),"citation":{"document_title":meta.get("document_title"),"authors":meta.get("authors",[]),"publication_date":meta.get("publication_date"),"source_type":meta.get("source_type"),"document_class":meta.get("document_class"),"revision_id":d["revision_id"],"canonical_object_type":d.get("parent_type") or d["source_object_type"],"canonical_object_id":d.get("parent_id"),"source_anchor_ids":list(d.get("anchors",())),"locator":locator if locator is not None else "EXACT_LOCATOR_UNAVAILABLE","identifier":meta.get("identifier"),"model_id":d.get("model_id"),"ranking_version":self.ranking_version},"reliability_signals":{k:meta.get(k) for k in ("peer_reviewed","ai_generated","citations_verified","evidence_type")},"review_state":meta.get("review_state"),"verification_state":meta.get("verification_state"),"temporal_status":meta.get("temporal_status"),"display_policy":policy,"collections":meta.get("collections",[]),"active":d.get("active",False),"index_version":d.get("version")}
 def _expand(self,q,policy,parent,d):
  if q.parent_expansion=="NONE" or not parent: return None
  allowed=policy=="FULL_TEXT_ALLOWED" or (policy=="INTERNAL_RESEARCH_ONLY" and q.internal_access and parent.get("internal_access_allowed",False))
  if not allowed: return {"denied":"DISPLAY_POLICY","metadata":{"type":d.get("parent_type"),"id":d.get("parent_id")}}
  mode=q.parent_expansion
  if mode=="AUTO": mode={"PROTOCOL":"COMPLETE_PROTOCOL","RESULT":"COMPLETE_RESULT_PACKAGE","TAXONOMIC_TREATMENT":"COMPLETE_TAXONOMIC_TREATMENT","IDENTIFICATION_KEY":"COMPLETE_IDENTIFICATION_KEY"}.get(d.get("parent_type"),"PARENT_METADATA")
  if mode=="PARENT_METADATA": return {"mode":mode,"metadata":{k:v for k,v in parent.items() if k not in {"complete_text","text"}},"complete_object":False}
  return {"mode":mode,"object":parent,"complete_object":True}
