import os
from scripts.build_086c_final_validation import api_contracts,performance,quality,validate
def test_quality_metrics_remain_review_ready():
 q=quality();assert q["corpus_size"]==19 and q["duplicate_precision"]==q["duplicate_recall"]==1 and q["contradiction_precision"]==q["contradiction_recall"]==1 and q["independent_source_accuracy"]==1 and q["false_consensus_rate"]==0 and q["anchors_preserved"]
def test_corrected_api_contracts():assert all(api_contracts().values())
def test_performance_stays_bounded():
 p=performance();assert p["completed"] and p["throughput"]>0 and p["peak_memory_bytes"]<100_000_000
def test_final_verdict_requires_postgres_validation():
 report=validate();configured=bool(os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL"));assert (report["verdict"]=="READY — BUILD-086 REVIEW READY")==configured
