import json
from pathlib import Path

import pytest

from scripts.oc_autonomy_certification import (
    CycleEvidence,
    append_cycle,
    evaluate,
    read_ledger,
    write_ledger,
)


def _sha(value: int) -> str:
    return f"{value:040x}"


def good(i, **kw):
    base = {
        "cycle_id": str(i),
        "work_identity": f"issue:{i}",
        "lease_identity": f"lease:{i}",
        "pr_number": 1500 + i,
        "exact_head_sha": _sha(1000 + i),
        "merged_sha": _sha(2000 + i),
        "verification_base_sha": _sha(3000 + i),
        "exact_head_ci_green": True,
        "landed_verified": True,
        "lease_released": True,
    }
    base.update(kw)
    return CycleEvidence(**base)


def test_ten_cycles_with_healed_fault_certifies():
    cycles = [good(i) for i in range(1, 11)]
    cycles[4] = good(5, recoverable_fault_seen=True, recoverable_fault_healed=True)
    result = evaluate(cycles)
    assert result.certified and result.accepted_streak == 10 and result.recovery_proven


def test_clean_ten_without_recovery_is_not_self_healing_certified():
    result = evaluate([good(i) for i in range(1, 11)])
    assert not result.certified
    assert result.accepted_streak == 10
    assert not result.recovery_proven


def test_unhealed_fault_stops_streak():
    cycles = [good(1), good(2, recoverable_fault_seen=True)]
    result = evaluate(cycles)
    assert not result.certified and result.accepted_streak == 1


def test_false_green_duplicate_owner_gate_and_manual_intervention_fail():
    for flag in (
        "false_green",
        "duplicate_ownership",
        "duplicate_lineage",
        "unauthorized_owner_gate_crossing",
        "abandoned_lease",
        "manual_intervention",
    ):
        assert not good(1, **{flag: True}).accepted


def test_missing_exact_head_or_merge_evidence_fails():
    assert not good(1, exact_head_sha="").accepted
    assert not good(1, merged_sha="").accepted
    assert not good(1, exact_head_ci_green=False).accepted
    assert not good(1, landed_verified=False).accepted


def test_malformed_exact_head_or_merge_identity_fails_closed():
    assert not good(1, exact_head_sha="abc123").accepted
    assert not good(1, merged_sha="g" * 40).accepted


def test_reused_durable_identity_stops_the_streak():
    duplicate_cases = (
        {"cycle_id": "1"},
        {"work_identity": "issue:1"},
        {"lease_identity": "lease:1"},
        {"pr_number": 1501},
        {"exact_head_sha": _sha(1001)},
        {"merged_sha": _sha(2001)},
    )
    for duplicate in duplicate_cases:
        result = evaluate([good(1), good(2, **duplicate)])
        assert not result.certified
        assert result.accepted_streak == 1
        assert "reused" in result.reason


def test_non_positive_target_fails_closed():
    result = evaluate([good(1)], target=0)
    assert not result.certified
    assert result.reason == "target must be positive"


def test_ledger_is_machine_readable_and_atomic_shape(tmp_path: Path):
    path = tmp_path / "certification.json"
    result = write_ledger(
        path,
        [good(1, recoverable_fault_seen=True, recoverable_fault_healed=True)],
    )
    data = json.loads(path.read_text())
    assert data["schema"] == "oc.autonomy.certification.v1"
    assert data["cycles"][0]["accepted"] is True
    assert data["result"]["certified"] is result.certified


def test_ledger_round_trip_preserves_cycle_evidence(tmp_path: Path):
    path = tmp_path / "certification.json"
    cycles = [good(1, recoverable_fault_seen=True, recoverable_fault_healed=True)]
    write_ledger(path, cycles)
    assert read_ledger(path) == cycles


def test_append_is_restart_safe_and_identical_replay_is_a_no_op(tmp_path: Path):
    path = tmp_path / "certification.json"
    first = good(1)
    append_cycle(path, first)
    before = path.read_bytes()

    result = append_cycle(path, first)

    assert path.read_bytes() == before
    assert result.accepted_streak == 1
    append_cycle(path, good(2))
    assert read_ledger(path) == [first, good(2)]


def test_append_refuses_identity_reuse_with_changed_evidence(tmp_path: Path):
    path = tmp_path / "certification.json"
    append_cycle(path, good(1))
    with pytest.raises(ValueError, match="reuses lease_identity"):
        append_cycle(path, good(2, lease_identity="lease:1"))


def test_writer_refuses_failed_aggregate_and_excess_cycles(tmp_path: Path):
    path = tmp_path / "certification.json"
    with pytest.raises(ValueError, match="failed aggregate"):
        write_ledger(path, [good(1), good(2, lease_identity="lease:1")])

    cycles = [good(i) for i in range(1, 12)]
    cycles[4] = good(5, recoverable_fault_seen=True, recoverable_fault_healed=True)
    with pytest.raises(ValueError, match="exceeds"):
        write_ledger(path, cycles)


def test_reader_refuses_persisted_failed_aggregate(tmp_path: Path):
    path = tmp_path / "certification.json"
    write_ledger(path, [good(1), good(2)])
    data = json.loads(path.read_text())
    data["cycles"][1]["lease_identity"] = "lease:1"
    data["result"].update(
        certified=False,
        accepted_streak=1,
        recovery_proven=False,
        reason="cycle 2 reused lease identity",
    )
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="failed aggregate"):
        read_ledger(path)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda data: data.update(schema="unknown"),
        lambda data: data.update(target_streak=9),
        lambda data: data["cycles"][0].update(accepted=False),
        lambda data: data["cycles"][0].update(extra="untrusted"),
        lambda data: data["result"].update(accepted_streak=99),
    ),
)
def test_reader_fails_closed_on_corrupt_or_inconsistent_ledger(
    tmp_path: Path, mutation
):
    path = tmp_path / "certification.json"
    write_ledger(path, [good(1)])
    data = json.loads(path.read_text())
    mutation(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_ledger(path)


def test_verification_base_is_required_and_distinct():
    assert not good(1, verification_base_sha="").accepted
    assert not good(1, verification_base_sha=_sha(1001)).accepted
    assert not good(1, verification_base_sha=_sha(2001)).accepted


def test_verification_base_identity_cannot_be_reused():
    base = _sha(3999)
    first = good(1, verification_base_sha=base)
    second = good(2, verification_base_sha=base)
    result = evaluate([first, second])
    assert not result.certified
    assert result.accepted_streak == 1
    assert "verification base" in result.reason


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cycle_id", 5),
        ("work_identity", ["work"]),
        ("lease_identity", {"lease": "x"}),
        ("pr_number", True),
        ("pr_number", "1539"),
        ("exact_head_sha", 123),
        ("merged_sha", None),
        ("verification_base_sha", 123),
        ("exact_head_ci_green", 1),
        ("landed_verified", "true"),
        ("lease_released", 1),
        ("duplicate_ownership", 0),
        ("duplicate_lineage", None),
        ("unauthorized_owner_gate_crossing", 0),
        ("abandoned_lease", 0),
        ("false_green", 0),
        ("recoverable_fault_seen", 0),
        ("recoverable_fault_healed", 0),
        ("manual_intervention", 0),
    ],
)
def test_wrong_scalar_evidence_types_fail_closed(field, value):
    cycle = good(5, **{field: value})
    assert cycle.accepted is False
