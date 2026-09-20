from pathlib import Path
import json
from scripts.oc_autonomy_certification import CycleEvidence, evaluate, write_ledger

def good(i, **kw):
    base=dict(cycle_id=str(i),work_identity=f"issue:{i}",lease_identity=f"lease:{i}",
              pr_number=1500+i,exact_head_sha=f"head{i}",merged_sha=f"merge{i}",
              exact_head_ci_green=True,landed_verified=True,lease_released=True)
    base.update(kw)
    return CycleEvidence(**base)

def test_ten_cycles_with_healed_fault_certifies():
    cycles=[good(i) for i in range(1,11)]
    cycles[4]=good(5,recoverable_fault_seen=True,recoverable_fault_healed=True)
    r=evaluate(cycles)
    assert r.certified and r.accepted_streak==10 and r.recovery_proven

def test_clean_ten_without_recovery_is_not_self_healing_certified():
    r=evaluate([good(i) for i in range(1,11)])
    assert not r.certified and r.accepted_streak==10 and not r.recovery_proven

def test_unhealed_fault_stops_streak():
    cycles=[good(1),good(2,recoverable_fault_seen=True)]
    r=evaluate(cycles)
    assert not r.certified and r.accepted_streak==1

def test_false_green_duplicate_owner_gate_and_manual_intervention_fail():
    for flag in ("false_green","duplicate_ownership","duplicate_lineage",
                 "unauthorized_owner_gate_crossing","abandoned_lease","manual_intervention"):
        assert not good(1, **{flag: True}).accepted

def test_missing_exact_head_or_merge_evidence_fails():
    assert not good(1, exact_head_sha="").accepted
    assert not good(1, merged_sha="").accepted
    assert not good(1, exact_head_ci_green=False).accepted
    assert not good(1, landed_verified=False).accepted

def test_ledger_is_machine_readable_and_atomic_shape(tmp_path: Path):
    p=tmp_path/"certification.json"
    r=write_ledger(p,[good(1,recoverable_fault_seen=True,recoverable_fault_healed=True)])
    data=json.loads(p.read_text())
    assert data["schema"]=="oc.autonomy.certification.v1"
    assert data["cycles"][0]["accepted"] is True
    assert data["result"]["certified"] is r.certified
