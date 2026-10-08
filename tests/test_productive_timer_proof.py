"""Productive evidence must reject idle cycles and duplicate lease identities."""

from types import SimpleNamespace

import pytest

from scripts.oc_program_autonomy_timer_proof import Proof, _parse


def _evidence():
    records, jobs, ledger = [], {}, []
    for index in range(10):
        key, identity = f"productive-{index}", f"job-{index}"
        records.append(
            {
                "attempted_jobs": 1,
                "completed_jobs": 1,
                "failed_jobs": 0,
                "jobs": [
                    {
                        "program_job_id": identity,
                        "job_key": key,
                        "outcome": "DELIVERED",
                    }
                ],
            }
        )
        jobs[key] = {
            "program_job_id": identity,
            "outcome": "DELIVERED",
            "attempt_count": 1,
            "lease_owner": None,
            "lease_token": None,
            "lease_expires_at": None,
        }
        ledger.extend(
            [
                {
                    "event": "start",
                    "program_job_id": identity,
                    "live_owned_lease": True,
                    "lease_fingerprint": f"lease-{index}",
                },
                {"event": "end", "program_job_id": identity},
            ]
        )
    proof = object.__new__(Proof)
    proof.args = SimpleNamespace(target_cycles=10)
    proof.assertions = []
    proof.settled_before_deadline = True
    proof.supervisors = [SimpleNamespace(cycles=lambda: records, cycle=lambda r: r)]
    return proof, records, jobs, ledger


@pytest.mark.parametrize("mutation", ["none", "idle", "lease", "persistence", "order"])
def test_productive_evidence_is_derived_not_inferred_from_timer_count(mutation):
    proof, records, jobs, ledger = _evidence()
    if mutation == "idle":
        records[4] = {"attempted_jobs": 0, "completed_jobs": 0, "jobs": []}
    elif mutation == "lease":
        ledger[2]["lease_fingerprint"] = ledger[0]["lease_fingerprint"]
    elif mutation == "persistence":
        jobs["productive-4"]["outcome"] = None
    elif mutation == "order":
        records[3], records[4] = records[4], records[3]
    proof.evaluate_productive(jobs, ledger)
    assert proof.assertions[-1]["passed"] is (mutation == "none")


def test_productive_scenario_requires_one_job_per_cycle_and_ten_cycles():
    base = ["--dsn", "postgresql://test@127.0.0.1/test", "--scenario", "productive"]
    args = _parse(base + ["--supervisors", "1", "--max-jobs-per-cycle", "1"])
    assert args.target_cycles == 10
    for invalid in [
        ["--supervisors", "2", "--max-jobs-per-cycle", "1"],
        ["--supervisors", "1", "--max-jobs-per-cycle", "2"],
        ["--supervisors", "1", "--max-jobs-per-cycle", "1", "--target-cycles", "9"],
    ]:
        with pytest.raises(SystemExit):
            _parse(base + invalid)
