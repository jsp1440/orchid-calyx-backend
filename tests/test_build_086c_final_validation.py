import json,subprocess,sys
from pathlib import Path
from scripts.build_086c_final_validation import api_validation,performance_validation,quality_validation,security_validation,validate
ROOT=Path(__file__).resolve().parents[1]

def test_quality_corpus_thresholds_and_required_composition():
 q=quality_validation();assert q["corpus_size"]>=18 and all(q["composition"].values());assert q["duplicate_detection"]["precision"]==q["duplicate_detection"]["recall"]==1;assert q["contradiction_detection"]["precision"]==q["contradiction_detection"]["recall"]==1
 assert q["independent_source_accuracy"]==1 and q["duplicate_inflation_prevented"] and q["false_consensus_rate"]==0 and q["taxonomic_ambiguity_routed"] and q["measurement_incompatibility_safe"] and q["anchors_preserved"] and q["malformed_records_rejected"]

def test_api_contract_audit_reports_exact_review_blockers():
 a=api_validation();assert a["authenticated"] and a["request_validation"] and not a["publication_endpoints"] and not a["immutable_evidence_mutation_endpoints"]
 assert not a["pagination"] and not a["deterministic_ordering"] and not a["not_found_responses"] and not a["unavailable_service_responses"] and len(a["gaps"])==4

def test_performance_concurrency_and_persistence_limit_are_measured():
 p=performance_validation();assert p["large_cluster_completed"] and p["concurrent_runs_completed"] and p["throughput_candidates_per_second"]>0 and p["peak_memory_bytes"]>0
 assert not p["transaction_isolation_validated"] and "in-memory" in p["blocker"]

def test_security_protected_schema_drive_and_publication_guards():
 s=security_validation();assert s["authorization_dependencies_present"] and s["literal_secret_scan_clear"] and s["protected_schema_writes"] and not s["google_drive_write_calls"] and not s["publication_calls"] and s["audit_history_present"]

def test_final_report_is_deterministic_not_ready_with_smallest_action():
 a=validate();b=validate();assert a["verdict"]==b["verdict"]=="NOT READY" and a["tested_main_commit"]==b["tested_main_commit"] and a["smallest_corrective_action"]
 assert a["migrations"]["present"]=={"086a_candidate_knowledge.sql":True,"086b_evidence_aggregation.sql":True} and not a["migrations"]["destructive_operations"]

def test_cli_emits_safe_json_report():
 result=subprocess.run([sys.executable,str(ROOT/"scripts/build_086c_final_validation.py")],cwd=ROOT,capture_output=True,text=True,check=True);report=json.loads(result.stdout);assert report["verdict"]=="NOT READY" and all(marker not in result.stdout for marker in ("gho_","sk-","BEGIN PRIVATE KEY"))
