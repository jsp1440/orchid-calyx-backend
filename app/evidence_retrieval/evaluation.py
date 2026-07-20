import math
def evaluate(cases,search):
 rows=[]
 for case in cases:
  result=search(case["query"]); ids=[r["citation"]["canonical_object_id"] for r in result["results"]]; expected=set(case["expected_ids"]); hits=[i for i,x in enumerate(ids,1) if x in expected]; k=max(1,len(ids)); precision=len(set(ids)&expected)/k; recall=len(set(ids)&expected)/max(1,len(expected)); rr=1/min(hits) if hits else 0; dcg=sum((1/math.log2(i+1)) for i in hits); ideal=sum(1/math.log2(i+1) for i in range(1,min(len(expected),k)+1)); citations=sum(bool(r["citation"]["revision_id"] and r["citation"]["source_anchor_ids"]) for r in result["results"])/k
  rows.append({"name":case["name"],"precision_at_k":precision,"recall_at_k":recall,"mrr":rr,"ndcg":dcg/ideal if ideal else 0,"source_diversity":len({r["citation"]["revision_id"] for r in result["results"]})/k,"duplicate_rate":result["deduplicated_count"]/max(1,result["total_candidates"]),"citation_completeness":citations,"parent_correctness":sum(r["canonical_parent"]["available"] for r in result["results"])/k,"copyright_correctness":sum(r["display_policy"]!="METADATA_ONLY" or r["authorized_excerpt"] is None for r in result["results"])/k})
 return {"cases":rows,"mean_mrr":sum(x["mrr"] for x in rows)/max(1,len(rows))}
