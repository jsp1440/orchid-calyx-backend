import os,socket
from urllib.parse import urlparse
import pytest
from scripts.build_086c_final_validation import api_contracts,performance,quality,validate
def test_quality_metrics_remain_review_ready():
 q=quality();assert q["corpus_size"]==19 and q["duplicate_precision"]==q["duplicate_recall"]==1 and q["contradiction_precision"]==q["contradiction_recall"]==1 and q["independent_source_accuracy"]==1 and q["false_consensus_rate"]==0 and q["anchors_preserved"]
def test_corrected_api_contracts():assert all(api_contracts().values())
def test_performance_stays_bounded():
 p=performance();assert p["completed"] and p["throughput"]>0 and p["peak_memory_bytes"]<100_000_000
def _postgres_reachable(dsn,timeout=0.5):
 # tests/conftest.py sets a placeholder DATABASE_URL so unrelated modules import
 # cleanly without a real database. postgres_validation() attempts a real
 # psycopg.connect() whenever DATABASE_URL is merely present, so this test
 # needs a genuinely reachable database, not just a configured-looking DSN,
 # or it fails with a raw driver connection error instead of a clean skip.
 if not dsn:return False
 try:
  parsed=urlparse(dsn)
  with socket.create_connection((parsed.hostname or "localhost",parsed.port or 5432),timeout=timeout):return True
 except OSError:return False
@pytest.mark.skipif(not _postgres_reachable(os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")),reason="no reachable PostgreSQL validation database")
def test_final_verdict_requires_postgres_validation():
 report=validate();assert report["verdict"]=="READY — BUILD-086 REVIEW READY"
